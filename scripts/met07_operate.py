#!/usr/bin/env python3
"""Reviewed adapter for the authorized MET-07 window. Fail closed; never retry an incident."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
import urllib.error
import urllib.request

import met07 as core
from met07_signals import SignalCollector, LogBuffer, SERVICES

BASE = "24620b231ef246d203f7220090bdacd039c717f9"


def read_url(url, metadata=False):
    headers = {"Metadata": "true"} if metadata else {}
    request = urllib.request.Request(url, headers=headers)
    # Never follow redirects, even on credential-free readiness requests.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    result = {"http_status": None, "connection_error": None}
    try:
        with opener.open(request, timeout=8) as response:
            result["http_status"] = response.status
            raw = response.read(2_000_001)
            core.require(len(raw) <= 2_000_000, "Readiness response too large")
            result["body"] = json.loads(raw)
    except urllib.error.HTTPError as error:
        result["http_status"] = error.code
    except (OSError, ValueError, urllib.error.URLError):
        result["connection_error"] = "connection_timeout_or_invalid_response"
    return result


def endpoint_checks(http):
    results = {}
    for name, base, path, role in (
        ("api", http.api, "/health/ready", None),
        ("analyst", http.api, "/v1/reception/counts", "analyst"),
        # A GET is deliberately used: no device/readings writes during preflight.
        ("producer", http.api, "/v1/reception/counts", "producer"),
        ("prometheus", http.prom, "/api/v1/query?query=time%28%29", None),
        ("jaeger", "http://127.0.0.1:26686", "/api/services", None),
        ("grafana", "http://127.0.0.1:23000", "/api/health", None),
    ):
        result = {"http_status": None, "connection_error": None}
        try:
            response = http.request(base, "GET", path, role=role)
            result.update(http_status=response["status"], connection_error=response.get("connection_error"),
                          server_date=response.get("server_date"), json_response=isinstance(response.get("body"), (dict, list)))
        except (OSError, TimeoutError, core.http.client.HTTPException):
            result["connection_error"] = "connection_or_timeout"
        results[name] = result
    # Producer is expected to be authenticated but forbidden on the analyst route.
    # 401 is never accepted as authentication proof; actual POST remains separately recorded.
    passed = all(not r["connection_error"] and r["http_status"] == (403 if n == "producer" else 200)
                 for n, r in results.items())
    return {"passed": passed, "results": results, "producer_check": "authenticated_role_forbidden_on_analyst_route"}


def power_check(external, now, reader=read_url, run=subprocess.run):
    scheduled = reader("http://169.254.169.254/metadata/scheduledevents?api-version=2020-07-01", True)
    compute = reader("http://169.254.169.254/metadata/instance/compute?api-version=2021-02-01", True)
    timers = run(["systemctl", "list-timers", "--all", "--no-pager", "--output=json"],
                 capture_output=True, text=True, timeout=5, check=False)
    cron = run(["sudo", "-n", "crontab", "-l"], capture_output=True, text=True, timeout=5, check=False)
    result = {"scheduled_events": {k: v for k, v in scheduled.items() if k != "body"},
              "compute": {k: compute.get("body", {}).get(k) for k in
                          ("name", "resourceGroupName", "subscriptionId", "vmId", "location")},
              "local_shutdown_pending": Path("/run/systemd/shutdown/scheduled").exists(),
              "timers_read": timers.returncode == 0, "external": external, "passed": False}
    events = scheduled.get("body", {}).get("Events")
    result["scheduled_event_count"] = len(events) if isinstance(events, list) else None
    # Do not retain arbitrary cron lines or environment values.
    cron_read = cron.returncode == 0 or (cron.returncode == 1 and "no crontab" in cron.stderr)
    result["root_cron_empty"] = cron_read and not cron.stdout.strip()
    try:
        timer_rows = json.loads(timers.stdout)
        result["timer_units"] = [r.get("unit") for r in timer_rows]
    except ValueError:
        result["timer_units"] = None
    checked = core.server_instant(external.get("checked_server_utc"))
    fresh = 0 <= now - checked.timestamp() < 300
    next_stop = core.server_instant(external.get("next_stop_utc"))
    result["passed"] = (scheduled["http_status"] == 200 and events == [] and
        compute["http_status"] == 200 and compute.get("body", {}).get("name") == "vm-eventos-b97e31-k3s" and
        not result["local_shutdown_pending"] and result["root_cron_empty"] and timers.returncode == 0 and
        not any(any(word in (unit or "").lower() for word in ("shutdown", "reboot", "poweroff"))
                for unit in result.get("timer_units") or []) and
        fresh and next_stop.timestamp() - now > 1200 and external.get("azure_schedules_verified") is True and
        external.get("active_power_workflows") == 0)
    return result


class VerifiedCollector(SignalCollector):
    """A live subprocess alone is insufficient: require a timestamped JSON record from each pipe."""
    def start_follow(self, server_start, evidence, spawn=subprocess.Popen):
        self.enabled()
        self.proofs = []
        try:
            for component in SERVICES:
                pods = self.pods(component)
                core.require(len(pods) == 1, "Exactly one log source required before degradation")
                for pod in pods:
                    # Tail proves the real stream without inducing a reading. Old timestamps are
                    # explicitly readiness-only; lifecycle collection still filters server windows.
                    args = [a for a in self.log_args(component, pod, server_start, True)
                            if not a.startswith("--since-time=")] + ["--tail=10"]
                    buffer = LogBuffer(component, pod["metadata"]["name"], pod["metadata"]["uid"],
                        sink=lambda entry: evidence.event("signal_log_candidate", source_scope=self.scope(), signal=entry))
                    proof = {"component": component, "pod_uid": pod["metadata"]["uid"], "records_received": 0,
                             "first_record_server_utc": None, "readiness_only": True, "failure": None}
                    child = spawn(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True)
                    def read_stream(process=child, target=buffer, status=proof):
                        try:
                            for line in process.stdout:
                                try:
                                    stamp, raw = line.strip().split(" ", 1)
                                    core.server_instant(stamp)
                                    value = json.loads(raw)
                                    core.require(isinstance(value, dict), "Non-object log")
                                    status["records_received"] += 1
                                    status["first_record_server_utc"] = status["first_record_server_utc"] or stamp
                                except (ValueError, RuntimeError):
                                    pass
                                with self.lock:
                                    if not target.feed(line):
                                        status["failure"] = "stream_truncated"
                                        process.terminate()
                                        break
                        except BaseException:
                            status["failure"] = "reader_failed"
                        finally:
                            process.stdout.close()
                    reader = threading.Thread(target=read_stream, daemon=True)
                    self.buffers.append(buffer)
                    self.followers.append((child, reader))
                    self.proofs.append(proof)
                    reader.start()
            until = time.monotonic() + 10
            while not all(p["records_received"] > 0 for p in self.proofs):
                core.require(time.monotonic() < until, "Log followers received no verifiable records")
                self.verify_live(require_records=False)
                time.sleep(0.1)
            self.verify_live()
            evidence.event("live_log_followers_verified", proofs=self.proofs)
        except BaseException:
            self.stop_follow()
            evidence.event("live_log_followers_failed", proofs=self.proofs)
            raise

    def verify_live(self, require_records=True):
        core.require(len(self.followers) == 2, "Both followers required")
        for (child, reader), proof in zip(self.followers, self.proofs):
            core.require(child.poll() is None and reader.is_alive() and not proof["failure"],
                         "Log follower is not functioning")
            core.require(not require_records or proof["records_received"] > 0, "No log transport proof")


def guard_probe(kube, state, parent, http):
    evidence = core.Evidence(parent / "watchdog-probe")
    state = {**state, "identity": evidence.identity, "boot_id": core.boot_id(), "run": uuid.uuid4().hex,
             "degraded_mono": time.monotonic()}
    state["deadline_mono"] = state["degraded_mono"] + core.LIMIT
    evidence.json("restore-state.json", state)
    guard = core.RemoteGuard()
    guard.arm(state, evidence.root)
    evidence.event("lease_probe_started_worker_unchanged", server_utc=core.utc(http.server_time()))
    # Intentionally stop heartbeat in this canary; worker remains 1/1 throughout.
    until = time.monotonic() + core.LEASE + 20
    while not (evidence.root / "guard-restored.json").exists():
        core.require(kube.ready(state), "Worker changed during guard canary")
        core.require(time.monotonic() < until, "Real watchdog restore probe timed out")
        time.sleep(1)
    result = core.read_private(evidence.root / "guard-restored.json", evidence.identity)
    core.require(result["run"] == state["run"] and result["uid"] == state["uid"] and
                 result["reason"] == "lost-supervisor" and result["within_deadline"] and kube.ready(state),
                 "Real watchdog restoration not verified")
    evidence.event("lease_probe_passed_worker_unchanged", server_utc=core.utc(http.server_time()), result=result)
    return result


class CheckedGuard(core.RemoteGuard):
    def __init__(self, collector_getter):
        self.collector_getter = collector_getter

    def arm(self, state, directory):
        self.collector_getter().verify_live()
        super().arm(state, directory)


def supervise(payload, directory):
    evidence = core.Evidence(directory)
    evidence.json("invocation.json", {"base_commit": BASE, "authorization": payload["authorization"],
        "rate_attempts_per_second": 2, "retries_of_incident": 0, "material": "REAL_PREFLIGHT_OR_INCIDENT"})
    http = core.Http()
    kube = core.Kubernetes("default", "eventos-development")
    try:
        for key in ("EVENT_PRODUCER_KEY", "EVENT_ANALYST_KEY"):
            core.require(bool(payload.get(key)), "Credential absent")
            os.environ[key] = payload.pop(key)
        state = kube.preflight(payload["authorization"]["deployment_uid"])
        evidence.json("refreshed-worker.json", state)
        endpoints = endpoint_checks(http)
        evidence.json("endpoint-preflight.json", endpoints)
        # Obtain the VM/server clock even if Prometheus is unavailable; it never
        # substitutes for Prometheus time in the actual Experiment.
        clock = time.time()
        power = power_check(payload["power_review"], clock)
        evidence.json("power-preflight.json", power)
        core.require(endpoints["passed"], "Endpoint/credential precondition failed; no device writes or degradation")
        core.require(power["passed"], "Scheduled shutdown verification incomplete; do not degrade")
        before = http.snapshot(kube.namespace)
        evidence.json("baseline.json", before)
        core.require(before["backlog"] == 0 and before["alert_state"] == "inactive", "Baseline not zero/inactive")
        guard_probe(kube, state, evidence.root, http)
        # Preflight followers do not need a registered device.
        collector = VerifiedCollector(kube, http, state["uid"], "met07-readiness-only", mode="real-read-only")
        try:
            collector.start_follow(before["server_utc"], evidence)
            collector.verify_live()
        finally:
            collector.stop_follow()
        evidence.json("preconditions-passed.json", {"passed": True, "server_utc": core.utc(http.server_time())})
        core.require(payload.get("execute_once") is True, "Preflight only; execution not requested")
        holder = {}
        def factory(k, h, uid, device):
            holder["collector"] = VerifiedCollector(k, h, uid, device, mode="real-read-only")
            return holder["collector"]
        guard = CheckedGuard(lambda: holder["collector"])
        # Distinct directory makes preflight logs unambiguously separate.
        experiment = core.Experiment(kube, http, guard, core.Evidence(evidence.root / "incident"), signals_factory=factory)
        experiment.run(payload["authorization"])
        evidence.json("result.json", {"passed": True, "incident_executed": True})
    except BaseException as error:
        evidence.json("adapter-failure.json", {"error_type": type(error).__name__,
            "reason": str(error) if isinstance(error, RuntimeError) else "operation_failed",
            "incident_directory_created": (evidence.root / "incident").exists(),
            "automatic_retry": False})
        raise


if __name__ == "__main__":
    os.umask(0o077)
    try:
        supervise(json.load(sys.stdin), Path(sys.argv[1]))
    except BaseException:
        print(json.dumps({"passed": False, "inspect": "adapter-failure.json", "automatic_retry": False}))
        sys.exit(1)
