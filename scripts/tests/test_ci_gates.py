"""Offline regression tests for the read-only CI gate audit."""

import copy
import importlib.util
import json
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    "ci_gates", Path(__file__).resolve().parents[1] / "verify-ci-gates.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.protection = {
            "required_status_checks": {
                "strict": True,
                "checks": [{"context": name, "app_id": 15368} for name in MODULE.REQUIRED],
            },
            "required_pull_request_reviews": {
                "required_approving_review_count": 1,
                "require_code_owner_reviews": True,
                "dismiss_stale_reviews": True,
            },
            "required_conversation_resolution": {"enabled": True},
            "enforce_admins": {"enabled": True},
        }
        self.pr = {
            "state": "OPEN", "isDraft": False, "baseRefName": "main",
            "mergeable": "MERGEABLE", "mergeStateStatus": "BLOCKED",
            "statusCheckRollup": [
                {"name": "quality", "status": "COMPLETED", "conclusion": "FAILURE"}
            ],
        }

    def test_valid_negative_control(self):
        self.assertEqual(MODULE.evaluate(self.protection, self.pr), [])

    def test_admin_exemption_missing_or_invalid_fails(self):
        for value in (None, {}, {"enabled": False}, {"enabled": "true"}):
            with self.subTest(value=value):
                protection = {**self.protection, "enforce_admins": value}
                self.assertIn(
                    "main protection must apply to administrators",
                    MODULE.evaluate(protection, self.pr),
                )

    def test_every_required_gate_is_checked(self):
        for name in MODULE.REQUIRED:
            with self.subTest(name=name):
                protection = copy.deepcopy(self.protection)
                protection["required_status_checks"]["checks"] = [
                    item for item in protection["required_status_checks"]["checks"]
                    if item["context"] != name
                ]
                self.assertTrue(MODULE.evaluate(protection, self.pr))

    def test_unbound_check_and_non_strict_protection_fail(self):
        self.protection["required_status_checks"]["checks"][0]["app_id"] = None
        self.assertTrue(MODULE.evaluate(self.protection, self.pr))
        self.setUp()
        self.protection["required_status_checks"]["strict"] = False
        self.assertTrue(MODULE.evaluate(self.protection, self.pr))

    def test_review_and_conversation_gates_are_required(self):
        for field in ("required_pull_request_reviews", "required_conversation_resolution"):
            with self.subTest(field=field):
                protection = copy.deepcopy(self.protection)
                protection.pop(field)
                self.assertTrue(MODULE.evaluate(protection, self.pr))

    def test_draft_closed_conflicting_or_unblocked_controls_fail(self):
        for key, value in (
            ("isDraft", True), ("state", "CLOSED"), ("state", "MERGED"),
            ("baseRefName", "other"), ("mergeable", "CONFLICTING"),
            ("mergeStateStatus", "CLEAN"), ("mergeStateStatus", "UNKNOWN"),
        ):
            with self.subTest(key=key, value=value):
                pr = {**self.pr, key: value}
                self.assertTrue(MODULE.evaluate(self.protection, pr))

    def test_skips_pending_success_and_unrequired_failures_do_not_count(self):
        for change in (
            {"conclusion": "SKIPPED"}, {"conclusion": "SUCCESS"},
            {"conclusion": "CANCELLED"}, {"status": "IN_PROGRESS"},
            {"name": "optional-check"},
        ):
            with self.subTest(change=change):
                pr = copy.deepcopy(self.pr)
                pr["statusCheckRollup"][0].update(change)
                self.assertTrue(MODULE.evaluate(self.protection, pr))

    def test_empty_responses_fail_closed(self):
        self.assertTrue(MODULE.evaluate({}, {}))

    def test_historical_snapshot_preserves_original_admin_exemption(self):
        path = Path(__file__).resolve().parents[2] / "docs/evidencia/DEV-03/control-negativo.json"
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(snapshot["passed"])
        self.assertEqual(
            MODULE.evaluate(snapshot["protection"], snapshot["negative_control"]),
            ["main protection must apply to administrators"],
        )

    def test_current_snapshot_enforces_admins_and_preserves_other_gates(self):
        path = Path(__file__).resolve().parents[2] / "docs/evidencia/DEV-03/proteccion-administradores.json"
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(MODULE.evaluate(snapshot["after"], self.pr), [])
        before = copy.deepcopy(snapshot["after"])
        before["enforce_admins"] = {"enabled": False}
        self.assertEqual(before, snapshot["before"])


if __name__ == "__main__":
    unittest.main()
