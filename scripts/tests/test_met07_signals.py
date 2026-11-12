"""Prepared signal collector tests. All HTTP, logs and processes are local fixtures."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import met07 as core
import met07_signals as signals

DEVICE = "fixture-device"


def fixture():
    attempts, rows, traces = [], [], []
    epoch = core.server_instant("2026-01-01T00:00:00Z").timestamp()
    for n in range(2):
        rid, tid, parent, worker = f"00000000-0000-4000-8000-{n:012d}", f"{n+1:032x}", f"{n+1:016x}", f"{n+101:016x}"
        start = {"kind": "attempt_started", "attempt": n, "event_id": f"e-{n}",
                 "device_id": DEVICE, "request_id": f"request-{n}", "phase": "during"}
        attempts.extend([start, {**start, "kind": "attempt_result", "http_status": 202,
                                 "reading_id": rid, "connection_error": None}])
        rows.append({"id": rid, "event_id": f"e-{n}", "device_id": DEVICE,
                     "received_at": "2026-01-01T00:00:00Z", "processed_at": "2026-01-01T00:00:01Z"})
        traces.append({"traceID": tid, "processes": {"api": {"serviceName": "event-service-api"},
            "worker": {"serviceName": "event-service-worker"}},
            "spans": [{"spanID": parent, "processID": "api", "operationName": "http_request",
                       "startTime": int((epoch-0.01)*1_000_000), "references": [], "tags": [
                           {"key": "route", "value": "/v1/readings"}, {"key": "status", "value": "202"},
                           {"key": "request_id", "value": f"request-{n}"},
                           {"key": "authorization", "value": "synthetic-credential-do-not-save"}]},
                      {"spanID": worker, "processID": "worker", "operationName": "process_reading",
                       "startTime": int((epoch+0.5)*1_000_000), "tags": [{"key": "reading_id", "value": rid}],
                       "references": [{"refType": "CHILD_OF", "traceID": tid, "spanID": parent}]}]})
    return attempts, rows, traces


def log_lines(component):
    _, rows, traces = fixture()
    output = []
    for n, row in enumerate(rows):
        output.append("2026-01-01T00:00:00.500Z " + json.dumps({
            "fields": {"reading_id": row["id"], "trace_id": traces[n]["traceID"],
                       "span_id": traces[n]["spans"][0 if component == "api" else 1]["spanID"],
                       "message": "synthetic-credential-do-not-save", "headers": {"X-API-Key": "synthetic-credential-do-not-save"}},
            "span": {"request_id": f"request-{n}"}}))
    return "\n".join(output) + "\n"


class Kube:
    context, namespace = "fixture-context", "met07-fixture"

    def __init__(self):
        self.calls, self.worker_absent, self.new_worker, self.wrong_uid = [], False, False, False

    def k(self, *args):
        self.calls.append(args)
        assert args[0] == "get", "No mutation permitted in signal fixture"
        kind = args[1]
        if kind.startswith("deployment/"):
            component = "worker" if kind.endswith("worker") else "api"
            return json.dumps({"metadata": {"uid": "foreign" if self.wrong_uid and component == "worker" else component+"-uid"}})
        component = "api" if "component=api" in args[3] else "worker"
        if kind == "replicaset":
            return json.dumps({"items": [{"metadata": {"uid": component+"-rs",
                "ownerReferences": [{"uid": component+"-uid", "controller": True}]}}]})
        assert kind == "pod"
        name = component + ("-new" if component == "worker" and self.new_worker else "-old")
        return json.dumps({"items": [] if component == "worker" and self.worker_absent else [{
            "metadata": {"name": name, "uid": name+"-uid",
                         "ownerReferences": [{"uid": component+"-rs", "controller": True}]}}]})

    def command(self, args):
        self.calls.append(args)
        assert "logs" in args and not any(a in args for a in ("patch", "scale", "restart"))
        component = args[args.index("-c")+1]
        return "" if component == "worker" and self.new_worker else log_lines(component)


class Http:
    def __init__(self):
        self.calls, self.status, self.error = [], 200, False
        self.traces = fixture()[2]

    def request(self, base, method, path):
        assert method == "GET", "Collector must not send load"
        self.calls.append(path)
        if self.error:
            raise TimeoutError()
        return {"status": self.status, "server_date": "Thu, 01 Jan 2026 00:00:00 GMT",
                "body": {"data": self.traces}}


class Child:
    def __init__(self, text):
        self.stdout = io.StringIO(text)
        self.stopped = False
    def poll(self):
        return 0
    def terminate(self):
        self.stopped = True
    def wait(self, timeout):
        return 0
    def kill(self):
        self.stopped = True


class SignalTests(unittest.TestCase):
    def setup_case(self, mode="fixture"):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        evidence = core.Evidence(Path(temp.name) / "signals")
        kube, http = Kube(), Http()
        collector = signals.SignalCollector(kube, http, "worker-uid", DEVICE, mode=mode)
        return collector, kube, http, evidence

    def collect(self, collector, evidence, phase="after"):
        attempts, rows, _ = fixture()
        return collector.collect(phase, {"start": "2026-01-01T00:00:02Z", "end": "2026-01-01T00:00:03Z"},
                                 attempts, rows, evidence)

    def test_default_is_prepared_and_never_executes_reads(self):
        collector, kube, http, evidence = self.setup_case("prepared")
        self.assertEqual(collector.plan()["material"], "PREPARED_COLLECTION_PLAN")
        with self.assertRaises(RuntimeError):
            self.collect(collector, evidence)
        self.assertEqual(kube.calls + http.calls, [])

    def test_final_uuid_log_trace_correlation_and_explicit_fixture_provenance(self):
        collector, _, _, evidence = self.setup_case()
        result = self.collect(collector, evidence)
        self.assertTrue(result["coverage"]["complete"])
        self.assertEqual(result["coverage"]["linked_uuid_count"], 2)
        self.assertEqual(result["material"], "FIXTURE_SIGNAL_OBSERVATION")
        self.assertFalse(result["collector_executed_incident"])

    def test_credentials_and_unapproved_fields_are_never_persisted(self):
        collector, _, _, evidence = self.setup_case()
        with patch.dict(core.os.environ, {"EVENT_PRODUCER_KEY": "synthetic-credential-do-not-save"}):
            self.collect(collector, evidence)
        text = (evidence.root / "signals-after.json").read_text()
        self.assertNotIn("synthetic-credential-do-not-save", text)
        self.assertNotIn("headers", text)
        self.assertNotIn("authorization", text)

    def test_server_windows_survive_local_clock_skew_and_include_http_parent(self):
        collector, _, http, evidence = self.setup_case()
        with patch.object(core.time, "time", return_value=4070908800):
            self.collect(collector, evidence)
        start = int(parse_qs(urlsplit(http.calls[0]).query)["start"][0])
        received = core.server_instant(fixture()[1][0]["received_at"]).timestamp() * 1_000_000
        self.assertLess(start, received)

    def test_missing_trace_parent_or_wrong_request_uuid_link_fails(self):
        for mode in ("parent", "request", "uuid"):
            collector, _, http, evidence = self.setup_case()
            if mode == "parent":
                http.traces[0]["spans"][1]["references"][0]["traceID"] = "f"*32
            elif mode == "request":
                http.traces[0]["spans"][0]["tags"][2]["value"] = "request-from-another-run"
            else:
                http.traces[0]["spans"][1]["tags"][0]["value"] = "00000000-0000-4000-8000-999999999999"
            with self.subTest(mode=mode), self.assertRaises(RuntimeError):
                self.collect(collector, evidence)
            result = json.loads((evidence.root / "signals-after.json").read_text())
            self.assertFalse(result["passed"])

    def test_http_and_connection_failure_have_distinct_metadata(self):
        for status, connection in ((503, False), (200, True)):
            collector, _, http, evidence = self.setup_case()
            http.status, http.error = status, connection
            with self.assertRaises(RuntimeError):
                self.collect(collector, evidence)
            query = json.loads((evidence.root / "signals-after.json").read_text())["queries"][0]
            self.assertEqual(query["http"], None if connection else status)
            self.assertEqual(query["connection_error"], connection)

    def test_wrong_worker_uid_and_foreign_rows_are_rejected(self):
        collector, kube, _, evidence = self.setup_case()
        kube.wrong_uid = True
        with self.assertRaises(RuntimeError):
            self.collect(collector, evidence)
        collector, _, _, evidence = self.setup_case()
        attempts, rows, _ = fixture()
        rows[0]["event_id"] = "wrong"
        with self.assertRaises(RuntimeError):
            collector.collect("after", {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:00:03Z"},
                              attempts, rows, evidence)

    def test_before_during_after_and_preservation_of_deleted_worker_log_stream(self):
        collector, kube, _, evidence = self.setup_case()
        calls = []
        def spawn(args, **kwargs):
            calls.append(args)
            return Child(log_lines(args[args.index("-c")+1]))
        collector.start_follow("2026-01-01T00:00:00Z", evidence, spawn=spawn)
        collector.stop_follow()
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("--follow=true" in command for command in calls))
        self.collect(collector, evidence, "before")
        kube.worker_absent = True
        self.collect(collector, evidence, "during")
        kube.worker_absent, kube.new_worker = False, True
        result = self.collect(collector, evidence)
        self.assertTrue(result["coverage"]["complete"])
        self.assertTrue(any(e["pod"] == "worker-old" for e in result["logs"]))
        self.assertTrue(any(e["kind"] == "signal_log_candidate" for e in evidence.records))
        recovered = signals.SignalCollector(kube, Http(), "worker-uid", DEVICE, mode="fixture")
        recovered.restore_buffers(evidence.records)
        self.assertTrue(recovered.buffers)

    def test_durable_stream_from_another_run_is_not_accepted(self):
        collector, _, _, _ = self.setup_case()
        with self.assertRaises(RuntimeError):
            collector.restore_buffers([{"kind": "signal_log_candidate", "source_scope": {"device_id": "other"}}])

    def test_truncated_logs_and_trace_limits_never_count_as_complete(self):
        collector, _, _, evidence = self.setup_case()
        buffer = signals.LogBuffer("worker", "fixture", "fixture-uid", limit=1)
        self.assertFalse(buffer.feed(log_lines("worker")))
        collector.buffers.append(buffer)
        with self.assertRaises(RuntimeError):
            self.collect(collector, evidence)
        collector, _, http, evidence = self.setup_case()
        http.traces *= 500
        with self.assertRaises(RuntimeError):
            self.collect(collector, evidence)
        data = json.loads((evidence.root / "signals-after.json").read_text())
        self.assertTrue(data["queries"][0]["limit_reached"])


if __name__ == "__main__":
    unittest.main()
