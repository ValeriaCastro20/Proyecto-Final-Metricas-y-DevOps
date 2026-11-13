"""Negative controls for the compulsory-load evidence verifier (no network)."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.parse


SPEC = importlib.util.spec_from_file_location(
    "esc3_evidence", Path(__file__).resolve().parents[1] / "esc3-evidence.py")
ESC3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ESC3)


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[2] / "docs/evidencia/ESC3/p3"

    def fixture(self, profile="extra"):
        return (json.loads((self.root / f"{profile}-load.json").read_text()),
                json.loads((self.root / f"{profile}-queries.json").read_text()))

    def test_all_compulsory_profiles(self):
        self.assertTrue(all(r["passed"] for r in ESC3.verify(self.root).values()))

    def test_corrupted_evidence_fails(self):
        report, evidence = self.fixture()
        changes = {
            "missing_reading": lambda r, e: e["after"]["readings"].pop(),
            "aggregate_includes_duplicates": lambda r, e: e["after"]["statistics"].update(count=1100),
            "wrong_average": lambda r, e: e["after"]["statistics"].update(temperature_avg=0),
            "late_not_late": lambda r, e: next(x for x in e["after"]["readings"]
                if x["event_id"] == "late-0").update(received_at="2000-01-01T00:00:00Z"),
            "wrong_order": lambda r, e: e["after"]["readings"].reverse(),
            "window_includes_upper_bound": lambda r, e: e["half_open"]["readings"].append(
                next(x for x in e["after"]["readings"] if x["event_id"] == "e-50")),
            "window_wrong_average": lambda r, e: e["half_open"]["statistics"].update(humidity_avg=0),
            "duplicate_wrong_uuid": lambda r, e: next(x for x in e["receipts"]
                if x["outcome"] == "duplicate").update(reading_id="not-original"),
            "missing_receipt": lambda r, e: e["receipts"].pop(),
            "accepted_receipt_wrong_device": lambda r, e: next(x for x in e["receipts"]
                if x["outcome"] == "accepted").update(device_id="another-device"),
            "duplicate_receipt_wrong_device": lambda r, e: next(x for x in e["receipts"]
                if x["outcome"] == "duplicate").update(device_id="another-device"),
            "pending_not_drained": lambda r, e: e["after"]["counters"].update(pending=1),
            "pending_in_statistics": lambda r, e: e["before"]["statistics"].update(count=1),
            "uncertain": lambda r, e: r.update(uncertain_requests=1),
            "lost": lambda r, e: r.update(lost_accepted=1),
            "payload_overwritten": lambda r, e: e["after"]["readings"][0].update(temperature=99),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                r, e = copy.deepcopy(report), copy.deepcopy(evidence)
                change(r, e)
                with self.assertRaises(RuntimeError):
                    ESC3.verify_profile("extra", r, e)

    def test_sustained_bounds_cannot_be_shortened(self):
        report, evidence = self.fixture("sustained")
        for patch in ({"emission_seconds": 119}, {"emission_seconds": 122},
                      {"target_rate": 21}, {"schedule_lag_ms_max": 1000},
                      {"unique_requested": 2399}):
            with self.subTest(patch=patch), self.assertRaises(RuntimeError):
                ESC3.verify_profile("sustained", {**report, **patch}, evidence)

    def test_manifest_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "evidence"
            shutil.copytree(self.root, destination)
            path = destination / "burst-load.json"
            path.write_text(path.read_text() + " ")
            result = subprocess.run([sys.executable, SPEC.origin, "--verify", str(destination)],
                                    capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Hash mismatch", result.stderr)

    def test_external_worker_is_observed_without_claiming_a_stopped_worker(self):
        report, evidence = self.fixture()
        evidence["processing_mode"] = "live-worker"
        evidence["before"] = copy.deepcopy(evidence["after"])
        self.assertTrue(ESC3.verify_profile("extra", report, evidence)["passed"])
        evidence["after"]["statistics"]["humidity_avg"] = 0
        with self.assertRaises(RuntimeError):
            ESC3.verify_profile("extra", report, evidence)

    def test_unknown_processing_mode_and_inconsistent_initial_counts_fail(self):
        for mode, counters in (("unverified", None), ("live-worker", {"pending": -1}),
                               ("live-worker", {"processed": 9999})):
            report, evidence = self.fixture()
            evidence["processing_mode"] = mode
            evidence["before"] = copy.deepcopy(evidence["after"])
            if counters:
                report["counters"].update(counters)
            with self.subTest(mode=mode, counters=counters), self.assertRaises(RuntimeError):
                ESC3.verify_profile("extra", report, evidence)

    def test_database_destination_overrides_rejected_before_any_command(self):
        base = "postgresql://user@127.0.0.1/esc3_test"
        ESC3.validate_database_url(base + "?sslmode=disable")
        for query in ("dbname=operational", "host=remote", "hostaddr=203.0.113.1",
                      "port=5433", "%64bname=operational", "host=", "dbname=esc3_test"):
            with self.subTest(query=query), self.assertRaises(RuntimeError):
                ESC3.validate_database_url(base + "?" + query)

    def test_resume_collects_missing_receipts_using_get_only(self):
        spec = importlib.util.spec_from_file_location(
            "esc3_resume", Path(SPEC.origin).with_name("esc3-resume-reads.py"))
        resume = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(resume)
        report, fixture = self.fixture("sustained")
        receipts = {r["id"]: r for r in fixture["receipts"]}
        observed = []

        class Opener:
            def open(inner, request, timeout):
                self.assertEqual(request.get_method(), "GET")
                parsed = urllib.parse.urlparse(request.full_url)
                query = urllib.parse.parse_qs(parsed.query)
                observed.append(parsed.path)
                if "/receipts/" in parsed.path:
                    value = receipts[parsed.path.rsplit("/", 1)[1]]
                elif parsed.path.endswith("/counts"):
                    value = fixture["after"]["counters"]
                else:
                    snapshot = fixture["half_open"] if query["to"][0].endswith("00:00:50Z") else fixture["after"]
                    if parsed.path.endswith("/statistics"):
                        value = snapshot["statistics"]
                    else:
                        offset = int(query["offset"][0])
                        value = snapshot["readings"][offset:offset + 1000]
                return io.StringIO(json.dumps(value))

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for profile in ESC3.PROFILES:
                r, e = self.fixture(profile)
                ESC3.write(directory / f"{profile}-load.json", r)
                if profile != "sustained":
                    e["processing_mode"] = "live-worker"
                    e["before"] = copy.deepcopy(e["after"])
                    ESC3.write(directory / f"{profile}-queries.json", e)
            with mock.patch.dict(os.environ, {"ESC3_BASE_URL": "http://127.0.0.1:18084",
                                             "EVENT_ANALYST_KEY": "fictitious"}), \
                    mock.patch.object(resume.urllib.request, "build_opener", return_value=Opener()):
                resume.resume(directory)
            self.assertTrue(all(r["passed"] for r in ESC3.verify(directory).values()))
            self.assertEqual(sum("/receipts/" in path for path in observed), 2400)


if __name__ == "__main__":
    unittest.main()
