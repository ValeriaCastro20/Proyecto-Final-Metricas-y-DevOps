"""Isolated operational precondition tests; no real watchdog, network or Kubernetes."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import met07 as core
import met07_operate as op


class OperationalTests(unittest.TestCase):
    def http(self, failure=None):
        fake = Mock()
        fake.api, fake.prom = "http://127.0.0.1:28000", "http://127.0.0.1:29090"
        def request(base, method, path, role=None):
            self.assertEqual(method, "GET")
            if failure == "timeout":
                raise TimeoutError()
            status = 403 if role == "producer" else 200
            if failure is not None and failure == role:
                status = 401
            return {"status": status, "body": {}, "server_date": "server", "connection_error": None}
        fake.request.side_effect = request
        return fake

    def test_endpoint_readiness_is_get_only_and_authenticated(self):
        self.assertTrue(op.endpoint_checks(self.http())["passed"])

    def test_invalid_producer_and_analyst_are_rejected(self):
        for role in ("producer", "analyst"):
            with self.subTest(role=role):
                self.assertFalse(op.endpoint_checks(self.http(role))["passed"])

    def test_listening_but_not_responding_is_rejected(self):
        result = op.endpoint_checks(self.http("timeout"))
        self.assertFalse(result["passed"])
        self.assertTrue(all(r["http_status"] is None and r["connection_error"] for r in result["results"].values()))

    def power(self, **changes):
        external = {"checked_server_utc": "2026-11-12T14:00:00Z", "next_stop_utc": "2026-11-13T05:00:00Z",
                    "azure_schedules_verified": True, "active_power_workflows": 0}
        external.update(changes)
        def reader(url, metadata):
            return {"http_status": 200, "body": {"Events": []} if "scheduledevents" in url else
                    {"name": "vm-eventos-b97e31-k3s"}}
        def run(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, "[]" if "systemctl" in args else "", "")
        return op.power_check(external, core.server_instant("2026-11-12T14:00:01Z").timestamp(), reader, run)

    def test_fixture_positive_power_preconditions(self):
        self.assertTrue(self.power()["passed"])

    def test_unverified_cloud_schedule_fails_closed(self):
        self.assertFalse(self.power(azure_schedules_verified=False)["passed"])

    def test_stale_review_active_workflow_and_near_shutdown_fail(self):
        for changes in ({"checked_server_utc": "2026-11-12T13:00:00Z"}, {"active_power_workflows": 1},
                        {"next_stop_utc": "2026-11-12T14:10:00Z"}):
            with self.subTest(changes=changes):
                self.assertFalse(self.power(**changes)["passed"])

    def test_popen_without_records_or_reader_is_insufficient(self):
        collector = op.VerifiedCollector(Mock(), Mock(), "uid", "device", mode="fixture")
        process, reader = Mock(), Mock()
        process.poll.return_value = None
        reader.is_alive.return_value = True
        collector.followers = [(process, reader), (process, reader)]
        collector.proofs = [{"records_received": 0, "failure": None} for _ in range(2)]
        with self.assertRaises(RuntimeError):
            collector.verify_live()
        collector.proofs[0]["records_received"] = collector.proofs[1]["records_received"] = 1
        collector.verify_live()
        reader.is_alive.return_value = False
        with self.assertRaises(RuntimeError):
            collector.verify_live()

    def test_failed_follower_prevents_guard_arm(self):
        collector = Mock()
        collector.verify_live.side_effect = RuntimeError("fixture failed")
        guard = op.CheckedGuard(lambda: collector)
        with patch.object(core.RemoteGuard, "arm") as arm:
            with self.assertRaises(RuntimeError):
                guard.arm({}, Path("/fixture"))
            arm.assert_not_called()

    def test_failed_precondition_prevents_writes_probe_and_experiment(self):
        with tempfile.TemporaryDirectory() as temp:
            kube = Mock()
            kube.preflight.return_value = {"uid": "fixture"}
            payload = {"authorization": {"deployment_uid": "fixture"}, "EVENT_PRODUCER_KEY": "fixture-only-p",
                       "EVENT_ANALYST_KEY": "fixture-only-a", "power_review": {}, "execute_once": True}
            with patch.object(op.core, "Kubernetes", return_value=kube), patch.object(op, "endpoint_checks", return_value={"passed": False}), \
                 patch.object(op, "power_check", return_value={"passed": False}), patch.object(op, "guard_probe") as probe, \
                 patch.object(core.Experiment, "run") as run, patch.dict(op.os.environ):
                with self.assertRaises(RuntimeError):
                    op.supervise(payload, Path(temp) / "run")
                probe.assert_not_called()
                run.assert_not_called()
                kube.scale.assert_not_called()
            self.assertFalse((Path(temp) / "run" / "incident").exists())
            failure = json.loads((Path(temp) / "run" / "adapter-failure.json").read_text())
            self.assertFalse(failure["automatic_retry"])


if __name__ == "__main__":
    unittest.main()
