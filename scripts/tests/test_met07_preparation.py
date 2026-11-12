"""Isolated MET-07 safety tests: no network, Kubernetes, SSH or incident."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("met07", ROOT / "scripts/met07.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class Clock:
    def __init__(self, value=0):
        self.value = value

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


def state():
    return {"context": "fixture", "namespace": "met07-fixture", "uid": "fixture-uid",
            "replicas": 1, "run": "fixture-run", "boot_id": "fixture-boot",
            "degraded_mono": 0, "deadline_mono": 600, "selector": M.SELECTOR}


def rule(status="inactive"):
    return {"status": "success", "data": {"groups": [{"rules": [{
        "name": M.RULE, "query": M.QUERY, "duration": 120, "health": "ok", "state": status,
        "alerts": [] if status != "firing" else [{
            "state": "firing", "labels": {"job": "event-service",
            "instance": "event-service.met07-fixture.svc.cluster.local:8000"}}],
    }]}]}}


def deployment():
    return {"metadata": {"uid": "fixture-uid", "resourceVersion": "10", "generation": 3},
            "spec": {"replicas": 1, "selector": {"matchLabels": copy.deepcopy(M.LABELS)},
                     "template": {"metadata": {"labels": copy.deepcopy(M.LABELS)}, "spec": {
                         "containers": [{"args": ["process"], "image": "fixture@sha256:abc"}]}}},
            "status": {"readyReplicas": 1, "availableReplicas": 1, "observedGeneration": 3}}


class FakeKube:
    context, namespace = "fixture", "met07-fixture"

    def __init__(self):
        self.replicas, self.scales, self.fail_zero, self.fail_restore = 1, [], False, 0

    def preflight(self, uid):
        M.require(uid == "fixture-uid", "UID")
        return {"context": self.context, "namespace": self.namespace, "uid": uid, "replicas": 1,
                "selector": M.SELECTOR, "image": "fixture"}

    def scale(self, saved, replicas):
        self.scales.append(replicas)
        self.replicas = replicas
        if replicas == 0 and self.fail_zero:
            raise RuntimeError("Uncertain scale outcome")
        if replicas == 1 and self.fail_restore:
            self.fail_restore -= 1
            raise RuntimeError("Temporary restore failure")

    def get(self):
        return {"spec": {"replicas": self.replicas}}

    def empty(self):
        return True

    def ready(self, saved):
        return self.replicas == saved["replicas"]


class FakeGuard:
    def __init__(self, fail=False):
        self.fail, self.armed, self.beats = fail, False, 0

    def arm(self, saved, directory):
        if self.fail:
            raise RuntimeError("Guard ACK absent")
        self.directory = directory
        self.armed = True

    def heartbeat(self):
        self.beats += 1

    def disarm(self):
        self.disarmed = True


class NoThread:
    def __init__(self, **kwargs):
        self.started = False

    def start(self):
        self.started = True

    def join(self, **kwargs):
        pass

    def is_alive(self):
        return False


class FakeHttp:
    api = "fixture-only-no-network"

    def __init__(self, clock, mode="normal"):
        self.clock, self.mode, self.during, self.n = clock, mode, 0, 0
        self.rows, self.device, self.experiment = [], None, None

    def request(self, base, method, path, payload=None, role=None):
        assert path == "/v1/devices"
        self.device = payload["id"]
        return {"status": 201, "server_date": "Wed, 01 Jan 2020 00:00:00 GMT", "body": {}}

    def snapshot(self, namespace, device=None):
        e = self.experiment
        if device and not e.load_stop.is_set():
            reading_id = f"00000000-0000-4000-8000-{self.n:012d}"
            event_id = f"e-{self.n}"
            e.evidence.event("attempt_started", attempt=self.n, event_id=event_id, phase=e.phase)
            e.evidence.event("attempt_result", attempt=self.n, event_id=event_id, phase=e.phase,
                             http_status=202, connection_error=None, reading_id=reading_id)
            self.rows.append({"id": reading_id, "event_id": event_id, "device_id": device,
                              "received_at": "2020-01-01T00:00:00Z", "processed_at": "2020-01-01T00:03:00Z"})
            self.n += 1
        status, backlog = "inactive", 0
        if e.phase == "during":
            self.during += 1
            status, backlog = ("pending" if self.during == 1 else "firing"), 128
            self.clock.sleep(125)
            if self.mode == "cancel":
                e.stop.set()
            elif self.mode == "timeout":
                self.clock.sleep(600)
            elif self.mode == "watchdog":
                (e.evidence.root / "guard-restored.json").write_text("{}")
            elif self.mode == "http-failure":
                raise RuntimeError("Fixture HTTP failure")
        return {"server_utc": M.utc(1577836800 + self.clock()), "server_sample_mono": self.clock(),
                "alert_state": status, "backlog": backlog, "counts": {"pending": 0, "accepted": self.n, "processed": self.n}}

    def get(self, base, path, role=None):
        return self.rows


class PreparationTests(unittest.TestCase):
    def test_plan_default_never_connects_or_mutates(self):
        with patch.object(sys, "argv", ["met07"]), patch.object(M.Http, "request", side_effect=AssertionError), \
                patch.object(M.subprocess, "run", side_effect=AssertionError), patch("sys.stdout", new_callable=io.StringIO) as out:
            M.main()
            plan = json.loads(out.getvalue())
        self.assertFalse(plan["execute_cli"])
        self.assertEqual(plan["maximum_degradation_seconds"], 600)
        self.assertEqual(plan["for_seconds"], 120)

    def test_cli_refuses_incident_execution(self):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/met07.py"), "execute"],
                                capture_output=True, timeout=10, check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_selector_matches_versioned_worker_and_rule_unchanged(self):
        manifest = json.loads((ROOT / "kubernetes/resources.json").read_text())
        items = [item for stage in manifest.values() if isinstance(stage, list) for item in stage]
        workers = [i for i in items if i.get("kind") == "Deployment" and i["metadata"]["name"] == M.WORKER]
        self.assertEqual(len(workers), 1)
        self.assertEqual(workers[0]["spec"]["selector"]["matchLabels"], M.LABELS)
        text = (ROOT / "kubernetes/observability/k8-prometheus.yaml").read_text()
        self.assertIn("expr: esc3_events_backlog_total > 100\n            for: 2m", text)

    def test_inactive_pending_and_firing_are_distinct(self):
        for value in ("inactive", "pending", "firing"):
            self.assertEqual(M.rule_state(rule(value), "met07-fixture"), value)

    def test_rule_errors_missing_and_wrong_target_never_pass(self):
        fixtures = []
        for change in ({"query": "esc3_events_backlog_total > 10"}, {"duration": 60}, {"health": "err"}, {"state": "unknown"}):
            b = rule()
            b["data"]["groups"][0]["rules"][0].update(change)
            fixtures.append(b)
        fixtures += [{"status": "error"}, {"status": "success", "data": {"groups": []}}]
        b = rule("firing")
        b["data"]["groups"][0]["rules"][0]["alerts"][0]["labels"]["instance"] = "another-namespace"
        fixtures.append(b)
        for b in fixtures:
            with self.subTest(b=b), self.assertRaises((RuntimeError, KeyError)):
                M.rule_state(b, "met07-fixture")

    def test_namespace_and_context_are_explicit(self):
        for ns in ("eventos-production", "default", "", "production"):
            with self.assertRaises(RuntimeError):
                M.Kubernetes("fixture", ns)
        with self.assertRaises(RuntimeError):
            M.Kubernetes("", "met07-fixture")

    def test_uid_and_resource_version_are_tested_atomically(self):
        d, commands = deployment(), []
        def command(args):
            commands.append(args)
            return json.dumps(d) if "get" in args else ""
        kube = M.Kubernetes("fixture", "met07-fixture", command)
        kube.scale(state(), 0)
        p = json.loads(commands[-1][-1])
        self.assertEqual([op["op"] for op in p], ["test", "test", "test", "replace"])
        self.assertEqual(p[0]["value"], "fixture-uid")
        self.assertEqual(p[1]["value"], "10")
        self.assertIn("--context", commands[-1])
        self.assertIn("met07-fixture", commands[-1])

    def test_replacement_uid_and_concurrent_scaling_are_not_modified(self):
        for changed in ("uid", "replicas", "already-zero", "unexpected-target"):
            d, calls = deployment(), []
            if changed == "uid":
                d["metadata"]["uid"] = "replacement"
            elif changed == "already-zero":
                d["spec"]["replicas"] = 0
            elif changed == "replicas":
                d["spec"]["replicas"] = 2
            def command(args):
                calls.append(args)
                return json.dumps(d)
            kube = M.Kubernetes("fixture", "met07-fixture", command)
            with self.assertRaises(RuntimeError):
                kube.scale(state(), 0 if changed == "already-zero" else 2 if changed == "unexpected-target" else 1)
            self.assertFalse(any("patch" in call for call in calls))

    def test_watchdog_restores_after_connection_or_supervisor_loss(self):
        for reason, now, heartbeat in [("lost-supervisor", 31, None), ("deadline", 541, 541)]:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as folder:
                saved = state()
                file = Path(folder) / "restore-state.json"
                file.write_text(json.dumps(saved))
                if heartbeat:
                    (Path(folder) / "heartbeat.json").write_text(json.dumps({"mono": heartbeat}))
                kube = FakeKube()
                kube.replicas = 0
                M.watchdog(file, Clock(now), lambda _: None, kube, "fixture-boot")
                result = json.loads((Path(folder) / "guard-restored.json").read_text())
                self.assertEqual(result["reason"], reason)
                self.assertTrue(result["within_deadline"])
                self.assertEqual(kube.replicas, 1)

    def test_watchdog_retries_restore_and_never_claims_unready_success(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "restore-state.json"
            file.write_text(json.dumps(state()))
            clock, kube = Clock(541), FakeKube()
            kube.fail_restore = 1
            M.watchdog(file, clock, clock.sleep, kube, "fixture-boot")
            self.assertEqual(kube.scales, [1, 1])
            self.assertTrue((Path(folder) / "guard-failure.json").exists())
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "restore-state.json"
            file.write_text(json.dumps(state()))
            kube = FakeKube()
            kube.ready = lambda _: False
            with self.assertRaises(InterruptedError):
                M.watchdog(file, Clock(541), lambda _: (_ for _ in ()).throw(InterruptedError()), kube, "fixture-boot")
            self.assertFalse((Path(folder) / "guard-restored.json").exists())

    def test_watchdog_rejects_boot_and_deadline_tampering(self):
        for change in ({"boot_id": "other"}, {"deadline_mono": 601}, {"replicas": 0}):
            with tempfile.TemporaryDirectory() as folder:
                saved = {**state(), **change}
                file = Path(folder) / "restore-state.json"
                file.write_text(json.dumps(saved))
                with self.assertRaises(RuntimeError):
                    M.watchdog(file, Clock(541), lambda _: None, FakeKube(), "fixture-boot")

    def test_gaps_include_no_request_boundaries_and_missed_schedule(self):
        records = [{"kind": "attempt_started", "mono": 1}, {"kind": "attempt_started", "mono": 2}]
        values = M.gaps(records, 0, 5)
        self.assertEqual(sum(x["seconds"] for x in values), 5)
        self.assertEqual(values[-1]["seconds"], 3)
        self.assertTrue(values[-1]["missed_schedule"])
        self.assertEqual(M.gaps([], 0, 5)[0]["seconds"], 5)

    def test_uuid_verification_rejects_missing_pending_foreign_or_uncertain(self):
        rid = "00000000-0000-4000-8000-000000000001"
        attempts = [{"kind": "attempt_started", "attempt": 0}, {
            "kind": "attempt_result", "attempt": 0, "event_id": "e-0",
            "http_status": 202, "connection_error": None, "reading_id": rid}]
        row = {"id": rid, "device_id": "fixture-device", "processed_at": "2020-01-01T00:00:00Z"}
        self.assertEqual(M.processed(attempts, [row], "fixture-device"), [rid])
        for rows in ([], [{**row, "processed_at": None}], [{**row, "device_id": "other"}], [row, row]):
            with self.assertRaises(RuntimeError):
                M.processed(attempts, rows, "fixture-device")
        for change in ({"http_status": 500}, {"connection_error": "timeout"}, {"reading_id": None}):
            altered = copy.deepcopy(attempts)
            altered[-1].update(change)
            with self.assertRaises(RuntimeError):
                M.processed(altered, [row], "fixture-device")
        with self.assertRaises(RuntimeError):
            M.processed(attempts[:1], [row], "fixture-device")

    def simulate(self, mode="normal", guard_fail=False, uncertain_scale=False):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        evidence = M.Evidence(Path(temp.name) / "run", clock=Clock())
        clock = evidence.clock
        kube, guard, http = FakeKube(), FakeGuard(guard_fail), FakeHttp(clock, mode)
        kube.fail_zero = uncertain_scale
        experiment = M.Experiment(kube, http, guard, evidence, clock, clock.sleep)
        http.experiment = experiment
        authorization = {"incident_authorized": True, "isolated": True, "isolation_review_ref": "fixture-review",
                         "context": "fixture", "namespace": "met07-fixture", "deployment_uid": "fixture-uid"}
        with patch.object(M.threading, "Thread", NoThread), patch.object(M.signal, "signal", return_value=None), \
                patch.object(M, "boot_id", return_value="fixture-boot"):
            try:
                experiment.run(authorization)
                error = None
            except RuntimeError as exc:
                error = exc
        return error, kube, guard, evidence

    def test_normal_path_requires_actual_firing_then_inactive_and_all_uuids(self):
        error, kube, guard, evidence = self.simulate()
        self.assertIsNone(error)
        self.assertEqual(kube.scales, [0, 1])
        events = [r["kind"] for r in evidence.records]
        self.assertLess(events.index("firing_observed"), events.index("restore_requested"))
        result = json.loads((evidence.root / "acceptance.json").read_text())
        self.assertTrue(result["passed"])
        self.assertGreater(len(result["processed_ids"]), 0)
        self.assertTrue(guard.armed)

    def test_guard_must_ack_before_degradation(self):
        error, kube, _, _ = self.simulate(guard_fail=True)
        self.assertIsNotNone(error)
        self.assertEqual(kube.scales, [])

    def test_failure_cancellation_and_timeout_restore_original_capacity(self):
        for mode in ("http-failure", "cancel", "timeout", "watchdog"):
            with self.subTest(mode=mode):
                error, kube, _, evidence = self.simulate(mode)
                self.assertIsNotNone(error)
                self.assertEqual(kube.scales[-1], 1)
                self.assertFalse((evidence.root / "acceptance.json").exists())

    def test_uncertain_zero_scale_result_still_enters_restoration(self):
        error, kube, _, _ = self.simulate(uncertain_scale=True)
        self.assertIsNotNone(error)
        self.assertEqual(kube.scales, [0, 1])

    def test_load_recorder_keeps_http_errors_connection_failure_and_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            clock = Clock()
            evidence = M.Evidence(Path(folder) / "run", clock)
            class Attempts:
                api = "fixture"
                n = 0
                def request(inner, *args):
                    inner.n += 1
                    if inner.n == 1:
                        raise TimeoutError()
                    if inner.n == 3:
                        experiment.load_stop.set()
                    return {"status": 503 if inner.n == 2 else 202, "body": {"reading_id": "fixture-id"},
                            "server_date": "Wed, 01 Jan 2020 00:00:00 GMT"}
            experiment = M.Experiment(FakeKube(), Attempts(), FakeGuard(), evidence, clock, clock.sleep)
            experiment.load("fixture")
            results = [r for r in evidence.records if r["kind"] == "attempt_result"]
            self.assertEqual(len(results), 3)
            self.assertIsNone(results[0]["http_status"])
            self.assertTrue(results[0]["connection_error"])
            self.assertEqual(results[1]["http_status"], 503)
            self.assertEqual(results[2]["reading_id"], "fixture-id")
            self.assertEqual(len([r for r in evidence.records if r["kind"] == "attempt_started"]), 3)

    def test_requires_authorization_and_isolation_before_any_operation(self):
        e = M.Experiment(None, None, None, None)
        for auth in ({}, {"incident_authorized": True}, {"incident_authorized": True, "isolated": False}):
            with self.assertRaises(RuntimeError):
                e.run(auth)

    def test_evidence_is_exclusive_and_credentials_never_written(self):
        with tempfile.TemporaryDirectory() as folder:
            evidence = M.Evidence(Path(folder) / "run")
            evidence.json("snapshot.json", {"fixture": True})
            with self.assertRaises(FileExistsError):
                evidence.json("snapshot.json", {})
            with self.assertRaises(FileExistsError):
                M.Evidence(evidence.root)
            with patch.dict(M.os.environ, {"EVENT_PRODUCER_KEY": "synthetic-fixture-value"}):
                with self.assertRaises(RuntimeError):
                    evidence.json("secret.json", {"value": "synthetic-fixture-value"})

    def test_preflight_saves_identity_and_rejects_foreign_worker_or_hpa(self):
        for mode in ("valid", "context", "selector", "owner", "hpa", "replicas", "generation"):
            with self.subTest(mode=mode):
                d = deployment()
                if mode == "selector":
                    d["spec"]["selector"]["matchLabels"] = {"app": "wrong"}
                if mode == "replicas":
                    d["spec"]["replicas"] = 2
                if mode == "generation":
                    d["status"]["observedGeneration"] = 0
                def command(args):
                    if args[-1] == "current-context":
                        return "other" if mode == "context" else "fixture"
                    if "auth" in args:
                        return "yes"
                    kind = args[args.index("get") + 1]
                    if kind == "deployment/" + M.WORKER:
                        return json.dumps(d)
                    if kind == "deployment":
                        items = [d]
                    elif kind == "replicaset":
                        items = [{"metadata": {"uid": "rs", "ownerReferences": [{"uid": "fixture-uid", "controller": True}]}}]
                    elif kind == "pod":
                        items = [{"metadata": {"ownerReferences": [{"uid": "wrong" if mode == "owner" else "rs", "controller": True}]},
                                  "status": {"phase": "Running"}}]
                    elif kind == "hpa":
                        items = [{"spec": {"scaleTargetRef": {"name": M.WORKER}}}] if mode == "hpa" else []
                    else:
                        raise AssertionError("Unexpected command")
                    return json.dumps({"items": items})
                kube = M.Kubernetes("fixture", "met07-fixture", command)
                if mode == "valid":
                    saved = kube.preflight("fixture-uid")
                    self.assertEqual(saved["replicas"], 1)
                    self.assertEqual(saved["uid"], "fixture-uid")
                    self.assertEqual(saved["selector"], M.SELECTOR)
                else:
                    with self.assertRaises(RuntimeError):
                        kube.preflight("fixture-uid")

    def test_ready_requires_controller_observation_of_current_generation(self):
        d = deployment()
        kube = M.Kubernetes("fixture", "met07-fixture", lambda args: json.dumps(d))
        self.assertTrue(kube.ready(state()))
        d["status"]["observedGeneration"] = 0
        self.assertFalse(kube.ready(state()))

    def test_late_timeout_attempts_restore_and_marks_deadline_exceeded(self):
        error, kube, _, evidence = self.simulate("timeout")
        self.assertIsNotNone(error)
        self.assertEqual(kube.replicas, 1)
        restored = [r for r in evidence.records if r["kind"] == "restore_requested"]
        self.assertTrue(restored[-1]["deadline_exceeded"])

    def test_http_keeps_status_when_response_body_connection_fails(self):
        class Connection:
            def __init__(inner, *args, **kwargs):
                pass
            def request(inner, *args):
                pass
            def getresponse(inner):
                return inner
            status = 503
            def getheader(inner, *args):
                return "Wed, 01 Jan 2020 00:00:00 GMT"
            def read(inner):
                raise TimeoutError()
            def close(inner):
                pass
        with patch.object(M.http.client, "HTTPConnection", Connection):
            result = M.Http().request("http://127.0.0.1:28000", "POST", "/v1/readings", {})
        self.assertEqual(result["status"], 503)
        self.assertEqual(result["connection_error"], "response_body_connection_or_timeout")

    def test_remote_guard_is_independent_and_rejects_foreign_ack(self):
        for wrong in (False, True):
            with self.subTest(wrong=wrong), tempfile.TemporaryDirectory() as folder:
                saved, calls = state(), []
                original_exists = Path.exists
                def exists(path):
                    return True if str(path) == "/run/systemd/system" else original_exists(path)
                def launch(args, **kwargs):
                    calls.append(args)
                    (Path(folder) / "guard-ready.json").write_text(json.dumps({
                        "run": saved["run"], "uid": "foreign" if wrong else saved["uid"]}))
                guard = M.RemoteGuard()
                with patch.object(M.sys, "platform", "linux"), patch.object(M, "boot_id", return_value="fixture-boot"), \
                        patch.object(M.subprocess, "run", side_effect=launch), patch.object(Path, "exists", exists):
                    if wrong:
                        with self.assertRaises(RuntimeError):
                            guard.arm(saved, folder)
                    else:
                        guard.arm(saved, folder)
                self.assertIn("systemd-run", calls[0])
                self.assertNotIn("--scope", calls[0])
                self.assertNotIn("--user", calls[0])
                self.assertIn("--property=Restart=on-failure", calls[0])
                self.assertIn("watchdog", calls[0])

    def test_local_wall_clock_offset_does_not_change_server_anchor(self):
        with tempfile.TemporaryDirectory() as folder:
            clock = Clock()
            evidence = M.Evidence(Path(folder) / "run", clock)
            http = FakeHttp(clock)
            experiment = M.Experiment(FakeKube(), http, FakeGuard(), evidence, clock, clock.sleep)
            http.experiment = experiment
            with patch.object(M.time, "time", return_value=4070908800):
                experiment.sample()
            self.assertEqual(evidence.anchor["server_utc"], "2020-01-01T00:00:00+00:00")
            self.assertEqual(evidence.anchor["source"], "prometheus_time_scalar")


if __name__ == "__main__":
    unittest.main()
