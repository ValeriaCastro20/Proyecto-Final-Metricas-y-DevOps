"""Negative identity/association tests; every process and file belongs to local fixtures."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("met07_hardened", ROOT / "scripts/met07.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def fixture():
    attempts, rows = [], []
    for n in range(2):
        rid = f"00000000-0000-4000-8000-{n:012d}"
        start = {"kind": "attempt_started", "attempt": n, "event_id": f"e-{n}",
                 "device_id": "fixture-device", "request_id": f"request-{n}", "phase": "during"}
        attempts.extend([start, {**start, "kind": "attempt_result", "http_status": 202,
                                 "connection_error": None, "reading_id": rid}])
        rows.append({"id": rid, "device_id": "fixture-device", "event_id": f"e-{n}",
                     "received_at": "2026-01-01T00:00:00Z", "processed_at": "2026-01-01T00:00:01Z"})
    return attempts, rows


class HardeningTests(unittest.TestCase):
    def test_exact_pairs_and_equivalent_zoned_server_timestamps(self):
        attempts, rows = fixture()
        rows[1]["processed_at"] = "2025-12-31T18:00:01-06:00"
        self.assertEqual(len(M.processed(attempts, rows, "fixture-device")), 2)

    def test_same_uuid_set_cannot_hide_swapped_event_associations(self):
        attempts, rows = fixture()
        rows[0]["event_id"], rows[1]["event_id"] = rows[1]["event_id"], rows[0]["event_id"]
        with self.assertRaises(RuntimeError):
            M.processed(attempts, rows, "fixture-device")

    def test_response_and_start_device_event_must_agree(self):
        for field in ("device_id", "event_id"):
            attempts, rows = fixture()
            attempts[1][field] = "other"
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                M.processed(attempts, rows, "fixture-device")

    def test_persisted_device_and_event_must_match_each_response(self):
        for field in ("device_id", "event_id"):
            attempts, rows = fixture()
            rows[0][field] = "other"
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                M.processed(attempts, rows, "fixture-device")

    def test_server_timestamps_reject_invalid_naive_missing_and_reversed(self):
        for field in ("received_at", "processed_at"):
            for value in (None, 0, "", "2026-01-01T00:00:00", "invalid", "2026-02-30T00:00:00Z"):
                attempts, rows = fixture()
                rows[0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                    M.processed(attempts, rows, "fixture-device")
        attempts, rows = fixture()
        rows[0]["processed_at"] = "2025-12-31T23:59:59Z"
        with self.assertRaises(RuntimeError):
            M.processed(attempts, rows, "fixture-device")

    def test_duplicate_starts_or_results_and_orphan_result_fail(self):
        attempts, rows = fixture()
        for altered in (attempts + [attempts[0]], attempts + [attempts[1]], attempts[1:]):
            with self.assertRaises(RuntimeError):
                M.processed(altered, rows, "fixture-device")

    def test_actual_cross_user_private_ack_heartbeat_and_results(self):
        helper = ROOT / "scripts/tests/met07_permissions_probe.py"
        args = [sys.executable, "-B", str(helper)]
        if os.geteuid() != 0:
            args = ["sudo", "-n", *args]
        env = {k: v for k, v in os.environ.items() if not k.startswith("EVENT_")}
        result = subprocess.run(args, capture_output=True, text=True, timeout=30, env=env, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["passed"])

    def test_identity_mismatch_rejected_before_kubernetes_or_http(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence = M.Evidence(Path(temp) / "run")
            changed = {**evidence.identity, "uid": evidence.identity["uid"] + 1}
            class Kube:
                context, namespace = "fixture", "met07-fixture"
                def preflight(self, uid):
                    raise AssertionError("Must reject identity before Kubernetes")
            authorization = {"incident_authorized": True, "isolated": True, "isolation_review_ref": "fixture",
                             "context": "fixture", "namespace": "met07-fixture", "deployment_uid": "fixture"}
            experiment = M.Experiment(Kube(), None, None, evidence)
            with patch.object(M, "actor_identity", return_value=changed), self.assertRaises(RuntimeError):
                experiment.run(authorization)

    def test_private_permissions_and_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence = M.Evidence(Path(temp) / "run")
            evidence.json("fixture.json", {})
            file = evidence.root / "fixture.json"
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            file.chmod(0o640)
            with self.assertRaises(RuntimeError):
                M.read_private(file, evidence.identity)
            file.chmod(0o600)
            link = evidence.root / "linked.json"
            link.symlink_to(file)
            with self.assertRaises(RuntimeError):
                M.read_private(link, evidence.identity)

    def test_foreign_watchdog_identity_does_not_write_ack(self):
        with tempfile.TemporaryDirectory() as temp:
            identity = M.actor_identity()
            state = {"identity": {**identity, "uid": identity["uid"] + 1}}
            path = Path(temp) / "restore-state.json"
            M.atomic_file(path, state)
            with self.assertRaises(RuntimeError):
                M.watchdog(path, kube=None)
            self.assertFalse((Path(temp) / "guard-ready.json").exists())

    def test_manifest_is_prepared_and_requires_server_boundaries(self):
        attempts, rows = fixture()
        for phase, stamp in (("before", "2026-01-01T00:00:00Z"), ("during", "2026-01-01T00:00:01Z"),
                             ("after", "2026-01-01T00:00:02Z")):
            attempts.append({"kind": "signal_phase_boundary", "phase": phase, "server_utc": stamp})
        attempts.append({"kind": "snapshot", "data": {"server_utc": "2026-01-01T00:00:03Z"}})
        result = M.signal_manifest(attempts, rows, "fixture-device")
        self.assertEqual(result["material"], "PREPARED_COLLECTION_PLAN")
        self.assertFalse(result["observations_collected"])
        altered = [r for r in attempts if not (r.get("kind") == "signal_phase_boundary" and r.get("phase") == "during")]
        with self.assertRaises(RuntimeError):
            M.signal_manifest(altered, rows, "fixture-device")


if __name__ == "__main__":
    unittest.main()
