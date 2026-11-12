"""Prepared MET-07 signal collection. Importing this module never contacts a service."""
import datetime as dt
import json
import re
import subprocess
import threading
from urllib.parse import urlencode

import met07 as core

SERVICES = {"api": "event-service-api", "worker": "event-service-worker"}
MAX_BYTES = 2_000_000
MAX_RECORDS = 8192
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TRACE_RE = re.compile(r"[0-9a-f]{32}")
SPAN_RE = re.compile(r"[0-9a-f]{16}")


def manifest(events, rows, device):
    return core.signal_manifest(events, rows, device)

class LogBuffer:
    """Keep only validated identifiers; no raw logs, messages, payloads or headers are retained."""
    def __init__(self, component, pod, pod_uid, limit=MAX_BYTES, sink=None):
        core.require(component in SERVICES, "Unknown log component")
        self.component, self.pod, self.pod_uid = component, pod, pod_uid
        self.limit, self.bytes, self.invalid, self.truncated = limit, 0, 0, False
        self.records = []
        self.sink = sink

    def feed(self, line):
        self.bytes += len(line.encode("utf8"))
        if self.bytes > self.limit or len(self.records) >= MAX_RECORDS:
            self.truncated = True
            return False
        try:
            stamp, raw = line.strip().split(" ", 1)
            instant = core.server_instant(stamp)
            value = json.loads(raw)
            fields = value.get("fields", {})
            span = value.get("span", {})
            rid = fields.get("reading_id") or span.get("reading_id")
            if not isinstance(rid, str) or not UUID_RE.fullmatch(rid):
                return True
            entry = {"server_utc": instant.isoformat(), "component": self.component, "pod": self.pod,
                     "pod_uid": self.pod_uid, "reading_id": rid}
            for key, pattern in (("trace_id", TRACE_RE), ("span_id", SPAN_RE), ("receipt_id", UUID_RE)):
                candidate = fields.get(key) or span.get(key)
                if isinstance(candidate, str) and pattern.fullmatch(candidate):
                    entry[key] = candidate
            request = fields.get("request_id") or span.get("request_id")
            if isinstance(request, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,128}", request):
                entry["request_id"] = request
            outcome = fields.get("outcome")
            if outcome in ("accepted", "duplicate", "processed", "rejected"):
                entry["outcome"] = outcome
            if self.sink:
                self.sink(entry)
            self.records.append(entry)
        except (ValueError, TypeError, AttributeError, RuntimeError):
            self.invalid += 1
        return True


class SignalCollector:
    def __init__(self, kube, http, deployment_uid, device, mode="prepared",
                 jaeger="http://127.0.0.1:26686"):
        core.require(mode in ("prepared", "fixture", "real-read-only"), "Explicit signal provenance required")
        self.kube, self.http, self.uid, self.device, self.mode, self.jaeger = kube, http, deployment_uid, device, mode, jaeger
        self.buffers, self.followers = [], []
        self.lock = threading.Lock()

    def plan(self):
        return {"material": "PREPARED_COLLECTION_PLAN", "network_executed": False,
                "scope": self.scope(), "phases": ["before", "during", "after"],
                "follow_before_scaling": True, "max_bytes_per_stream": MAX_BYTES}

    def scope(self):
        return {"context": self.kube.context, "namespace": self.kube.namespace,
                "deployment_uid": self.uid, "device_id": self.device}

    def enabled(self):
        core.require(self.mode != "prepared", "Prepared collector cannot execute reads without explicit mode")

    def pods(self, component):
        self.enabled()
        deployment = SERVICES[component]
        d = json.loads(self.kube.k("get", "deployment/" + deployment, "-o", "json"))
        if component == "worker":
            core.require(d["metadata"]["uid"] == self.uid, "Worker UID changed during collection")
        selector = f"app.kubernetes.io/name=event-service,app.kubernetes.io/component={component}"
        replicasets = json.loads(self.kube.k("get", "replicaset", "-l", selector, "-o", "json"))["items"]
        owners = {r["metadata"]["uid"] for r in replicasets if any(
            o.get("uid") == d["metadata"]["uid"] and o.get("controller")
            for o in r["metadata"].get("ownerReferences", []))}
        pods = json.loads(self.kube.k("get", "pod", "-l", selector, "-o", "json"))["items"]
        for pod in pods:
            core.require(any(o.get("uid") in owners and o.get("controller")
                for o in pod["metadata"].get("ownerReferences", [])), "Foreign log Pod")
        return pods

    def log_args(self, component, pod, since, follow=False):
        core.server_instant(since)
        name = pod["metadata"]["name"]
        core.require(re.fullmatch(r"[a-z0-9.-]+", name), "Invalid Pod name")
        args = ["sudo", "-n", "k3s", "kubectl", "--context", self.kube.context,
                "--namespace", self.kube.namespace, "logs", "pod/" + name, "-c", component,
                "--timestamps=true", "--since-time=" + since]
        # Follow until stopped/Pod deletion; LogBuffer enforces its own hard byte limit.
        return args + (["--follow=true"] if follow else ["--limit-bytes=" + str(MAX_BYTES)])

    def start_follow(self, server_start, evidence, spawn=subprocess.Popen):
        """Future authorized read-only operation; call before any worker Pod is removed."""
        self.enabled()
        evidence.check_access()
        for component in SERVICES:
            for pod in self.pods(component):
                args = self.log_args(component, pod, server_start, follow=True)
                buffer = LogBuffer(component, pod["metadata"]["name"], pod["metadata"]["uid"], sink=lambda entry:
                    evidence.event("signal_log_candidate", source_scope=self.scope(), signal=entry))
                child = spawn(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                              start_new_session=True)
                def read_stream(process=child, target=buffer):
                    try:
                        for line in process.stdout:
                            with self.lock:
                                if not target.feed(line):
                                    process.terminate()
                                    break
                    finally:
                        process.stdout.close()
                reader = threading.Thread(target=read_stream, daemon=True)
                self.buffers.append(buffer)
                self.followers.append((child, reader))
                reader.start()

    def restore_buffers(self, events):
        """Recover the sanitized durable stream after cancellation; no network or incident claim."""
        grouped = {}
        for event in events:
            if event.get("kind") != "signal_log_candidate":
                continue
            core.require(event.get("source_scope") == self.scope(), "Signal stream from another run/context")
            entry = event["signal"]
            key = (entry["component"], entry["pod"], entry["pod_uid"])
            buffer = grouped.setdefault(key, LogBuffer(*key))
            count = len(buffer.records)
            buffer.feed(entry["server_utc"] + " " + json.dumps({"fields": entry}))
            core.require(len(buffer.records) == count + 1, "Invalid durable signal candidate")
        self.buffers.extend(grouped.values())

    def stop_follow(self):
        for child, reader in self.followers:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
            reader.join(timeout=2)
            core.require(not reader.is_alive(), "Log reader did not stop")

    @staticmethod
    def safe_trace(trace, allowed_requests):
        tid = trace["traceID"]
        core.require(isinstance(tid, str) and TRACE_RE.fullmatch(tid), "Invalid trace ID")
        processes = {pid: {"serviceName": p["serviceName"]} for pid, p in trace["processes"].items()
                     if p.get("serviceName") in SERVICES.values()}
        spans = []
        for span in trace["spans"]:
            if span["processID"] not in processes or span["operationName"] not in ("http_request", "process_reading"):
                continue
            core.require(SPAN_RE.fullmatch(span["spanID"]), "Invalid span ID")
            stamp = span["startTime"] / 1_000_000
            core.require(stamp > 0, "Invalid server span time")
            tags = {}
            for tag in span.get("tags", []):
                key, value = tag["key"], tag["value"]
                if (key == "reading_id" and isinstance(value, str) and UUID_RE.fullmatch(value) or
                    key == "request_id" and value in allowed_requests or
                    key == "route" and value == "/v1/readings" or
                    key == "status" and str(value) in ("200", "202")):
                    tags[key] = value
            refs = [{"refType": r["refType"], "traceID": r["traceID"], "spanID": r["spanID"]}
                    for r in span.get("references", []) if r.get("refType") == "CHILD_OF" and
                    isinstance(r.get("traceID"), str) and TRACE_RE.fullmatch(r["traceID"]) and
                    isinstance(r.get("spanID"), str) and SPAN_RE.fullmatch(r["spanID"])]
            spans.append({"spanID": span["spanID"], "operationName": span["operationName"],
                          "processID": span["processID"], "server_utc": core.utc(stamp), "tags": tags, "references": refs})
        return {"traceID": tid, "processes": processes, "spans": spans}

    def collect(self, phase, window, attempts, rows, evidence):
        self.enabled()
        evidence.check_access()
        core.require(phase in ("before", "during", "after"), "Invalid collection phase")
        associations, unresolved = core.attempt_associations(attempts, self.device, strict=False)
        start, end = core.server_instant(window["start"]), core.server_instant(window["end"])
        core.require(start <= end, "Reversed server window")
        for row in rows:
            core.require(row["id"] in associations and
                         (row["device_id"], row["event_id"]) == associations[row["id"]]["pair"], "Foreign signal row")
            received = core.server_instant(row["received_at"])
            if phase == "after":
                finished = core.server_instant(row["processed_at"])
                core.require(finished >= received, "Invalid durable processing time")
                start, end = min(start, received), max(end, finished)
        # Include the HTTP parent that starts just before durable reception.
        query_start, query_end = start - dt.timedelta(seconds=60), end + dt.timedelta(seconds=60)
        result = {"material": "FIXTURE_SIGNAL_OBSERVATION" if self.mode == "fixture" else "REAL_READ_ONLY_SIGNAL_OBSERVATION",
                  "collector_executed_incident": False, "scope": self.scope(), "phase": phase,
                  "requested_server_window": window, "query_server_window": {
                      "start": query_start.isoformat(), "end": query_end.isoformat()},
                  "unresolved_attempts": unresolved, "queries": [], "logs": [], "traces": [], "passed": False}
        try:
            traces = {}
            for component, service in SERVICES.items():
                path = "/api/traces?" + urlencode({"service": service, "start": int(query_start.timestamp()*1_000_000),
                    "end": int(query_end.timestamp()*1_000_000), "limit": 1000})
                query = {"service": service, "http": None, "connection_error": False}
                result["queries"].append(query)
                try:
                    response = self.http.request(self.jaeger, "GET", path)
                except (OSError, TimeoutError):
                    query["connection_error"] = True
                    raise RuntimeError("Signal connection failure")
                query["http"] = response["status"]
                core.require(response["status"] == 200 and not response.get("connection_error"), "Signal HTTP failure")
                body = response["body"]
                core.require(isinstance(body, dict) and not body.get("errors") and isinstance(body.get("data"), list),
                             "Invalid Jaeger response")
                query["limit_reached"] = len(body["data"]) >= 1000
                for raw in body["data"]:
                    request_ids = {request for a in associations.values() for request in a["request_ids"]}
                    trace = self.safe_trace(raw, request_ids)
                    for span in trace["spans"]:
                        span["inside_requested_phase"] = (core.server_instant(window["start"]) <=
                            core.server_instant(span["server_utc"]) <= core.server_instant(window["end"]))
                    if any(s["tags"].get("reading_id") in associations or s["tags"].get("request_id") in request_ids
                           for s in trace["spans"]):
                        traces[trace["traceID"]] = trace
                for pod in self.pods(component):
                    buffer = LogBuffer(component, pod["metadata"]["name"], pod["metadata"]["uid"])
                    raw_log = self.kube.command(self.log_args(component, pod, query_start.isoformat()))
                    for line in raw_log.splitlines():
                        if not buffer.feed(line):
                            break
                    self.buffers.append(buffer)
            result["traces"] = list(traces.values())
            with self.lock:
                buffers = list(self.buffers)
                for buffer in buffers:
                    for entry in buffer.records:
                        stamp = core.server_instant(entry["server_utc"])
                        if entry["reading_id"] in associations and query_start <= stamp <= query_end:
                            result["logs"].append({**entry, "inside_requested_phase":
                                core.server_instant(window["start"]) <= stamp <= core.server_instant(window["end"])})
            covered = {}
            for trace in traces.values():
                for worker in trace["spans"]:
                    rid = worker["tags"].get("reading_id")
                    if worker["operationName"] != "process_reading" or rid not in associations:
                        continue
                    if trace["processes"][worker["processID"]]["serviceName"] != SERVICES["worker"]:
                        continue
                    parents = [r for r in worker["references"] if r["traceID"] == trace["traceID"]]
                    parent = next((s for s in trace["spans"] if any(r["spanID"] == s["spanID"] for r in parents)), None)
                    if (parent and parent["operationName"] == "http_request" and
                        trace["processes"][parent["processID"]]["serviceName"] == SERVICES["api"] and
                        parent["tags"].get("route") == "/v1/readings" and
                        str(parent["tags"].get("status")) in ("200", "202") and
                        parent["tags"].get("request_id") in associations[rid]["request_ids"]):
                        covered.setdefault(rid, set()).add(trace["traceID"])
            complete = not unresolved and not any(b.truncated for b in buffers) and not any(
                q["limit_reached"] for q in result["queries"])
            for rid in associations:
                complete = complete and bool(covered.get(rid)) and all(any(
                    e["reading_id"] == rid and e["component"] == c and e.get("trace_id") in covered.get(rid, set())
                    for e in result["logs"]) for c in SERVICES)
            result["coverage"] = {"scope": "accepted_reading_lifecycle_not_continuous_phase_coverage",
                                  "accepted_uuid_count": len(associations), "linked_uuid_count": len(covered),
                                  "complete": bool(associations) and bool(complete),
                                  "truncated_streams": sum(b.truncated for b in buffers)}
            if phase == "after":
                core.processed(attempts, rows, self.device)
                core.require(result["coverage"]["complete"], "Incomplete final log/trace correlation")
            result["passed"] = True
        except Exception as error:
            result["failure"] = type(error).__name__
            raise
        finally:
            evidence.json("signals-" + phase + ".json", result)
        return result
