#!/usr/bin/env python3
"""Read-only DEV-03 audit. Uses gh authentication; never attempts a merge."""

import argparse
import datetime
import json
from pathlib import Path
import subprocess
import sys


REQUIRED = {"quality", "postgres", "container", "secrets"}


def evaluate(protection, pr):
    """Fail closed unless the required gates and a live negative control exist."""
    errors = []
    status = protection.get("required_status_checks") or {}
    checks = {item.get("context"): item.get("app_id") for item in status.get("checks", [])}
    for name in sorted(REQUIRED):
        if checks.get(name) != 15368:
            errors.append(f"{name}: required GitHub Actions check missing or unbound")
    if status.get("strict") is not True:
        errors.append("main must require an up-to-date branch")
    if (protection.get("enforce_admins") or {}).get("enabled") is not True:
        errors.append("main protection must apply to administrators")
    reviews = protection.get("required_pull_request_reviews") or {}
    if reviews.get("required_approving_review_count", 0) < 1:
        errors.append("human approval not required")
    if reviews.get("require_code_owner_reviews") is not True:
        errors.append("CODEOWNERS approval not required")
    if reviews.get("dismiss_stale_reviews") is not True:
        errors.append("stale approvals are not dismissed")
    if (protection.get("required_conversation_resolution") or {}).get("enabled") is not True:
        errors.append("unresolved conversations do not block integration")
    if pr.get("state") != "OPEN" or pr.get("isDraft") is not False:
        errors.append("negative control must be an open, non-draft PR")
    if pr.get("baseRefName") != "main":
        errors.append("negative control must target main")
    if pr.get("mergeable") != "MERGEABLE":
        errors.append("negative control must be free of merge conflicts")
    if pr.get("mergeStateStatus") != "BLOCKED":
        errors.append("GitHub does not report the negative control as BLOCKED")
    failed = [
        item.get("name") for item in pr.get("statusCheckRollup", [])
        if item.get("name") in REQUIRED
        and item.get("status") == "COMPLETED"
        and item.get("conclusion") == "FAILURE"
    ]
    if not failed:
        errors.append("negative control has no completed failing required check")
    return errors


def gh_json(*args):
    return json.loads(subprocess.check_output(["gh", *args], text=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="marchelo23/Proyecto-Final-Metricas-y-DevOps")
    parser.add_argument("--negative-pr", required=True, type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        raw = gh_json("api", f"repos/{args.repo}/branches/main/protection")
        # Keep only public gate configuration, not an unbounded API response.
        protection = {key: raw.get(key) for key in (
            "required_status_checks", "required_pull_request_reviews",
            "required_conversation_resolution", "enforce_admins",
        )}
        pr = gh_json(
            "pr", "view", str(args.negative_pr), "--repo", args.repo, "--json",
            "number,url,state,isDraft,baseRefName,headRefOid,mergeable,mergeStateStatus,statusCheckRollup",
        )
        errors = evaluate(protection, pr)
        result = {
            "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "repository": args.repo,
            "protection": protection,
            "negative_control": pr,
            "errors": errors,
            "passed": not errors,
            "limitations": [
                "No merge attempted; review requirements may also block this PR.",
                "Administrator enforcement is checked; an administrator can still change repository protection settings.",
                "Not evidence of an independent human review or an academic defense.",
            ],
        }
        encoded = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            args.output.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return int(bool(errors))
    except (subprocess.CalledProcessError, OSError, ValueError) as error:
        print(f"CI gate audit failed ({type(error).__name__}); no acceptance recorded.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
