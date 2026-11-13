#!/usr/bin/env python3
"""Finish external P3 evidence using GET only; never reissue the completed load."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import urllib.parse
import urllib.request


SPEC = importlib.util.spec_from_file_location("esc3_evidence", Path(__file__).with_name("esc3-evidence.py"))
CORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CORE)


def resume(directory):
    CORE.require(not (directory / "manifest.json").exists(), "Evidence already finalized; do not overwrite it")
    base = os.environ["ESC3_BASE_URL"].rstrip("/")
    endpoint = urllib.parse.urlparse(base)
    CORE.require(endpoint.scheme in ("http", "https") and endpoint.hostname in ("localhost", "127.0.0.1")
                 and not endpoint.username and not endpoint.password and not endpoint.query
                 and not endpoint.fragment and endpoint.path in ("", "/"), "Loopback tunnel required")
    key = os.environ["EVENT_ANALYST_KEY"]
    started = dt.datetime.now(dt.timezone.utc).isoformat()

    def get(path):
        # Separate opener per request, no shared transport state between reader threads.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), CORE.NoRedirect())
        request = urllib.request.Request(base + path, method="GET", headers={"X-API-Key": key})
        with opener.open(request, timeout=15) as response:
            return json.load(response)

    def snapshot(device, window):
        readings = []
        for offset in range(0, 10000, 1000):
            page = get(f"/v1/devices/{device}/readings?" +
                       urllib.parse.urlencode({**window, "limit": 1000, "offset": offset}))
            readings.extend(page)
            if len(page) < 1000:
                break
        else:
            raise RuntimeError("Pagination exceeded compulsory bounds")
        return {"readings": readings,
                "statistics": get(f"/v1/devices/{device}/statistics?" + urllib.parse.urlencode(window)),
                "counters": get("/v1/reception/counts?" + urllib.parse.urlencode({"device_id": device}))}

    for profile in CORE.PROFILES:
        report = json.loads((directory / f"{profile}-load.json").read_text())
        CORE.require(report["profile"] == profile and report["passed"] is True,
                     "Completed successful generator reports required; never reissue load here")
        queries = directory / f"{profile}-queries.json"
        if queries.exists():
            evidence = json.loads(queries.read_text())
            CORE.require(evidence.get("processing_mode") == "live-worker", "External evidence required")
            CORE.verify_profile(profile, report, evidence)
            print(f"PASS existing {profile}", flush=True)
            continue
        device = report["device_id"]
        evidence = {"processing_mode": "live-worker", "window": CORE.WINDOW,
                    "before": snapshot(device, CORE.WINDOW)}
        CORE.require(evidence["before"]["counters"]["pending"] == 0, "Wait for live worker; no drain is performed")
        with ThreadPoolExecutor(max_workers=8) as readers:
            evidence["receipts"] = list(readers.map(
                lambda rid: get(f"/v1/receipts/{rid}"), report["receipt_ids"]))
        evidence["after"] = snapshot(device, CORE.WINDOW)
        evidence["half_open"] = snapshot(device, {**CORE.WINDOW, "to": "2040-01-01T00:00:50Z"})
        CORE.verify_profile(profile, report, evidence)
        CORE.write(queries, evidence)
        print(f"PASS resumed {profile}", flush=True)
    CORE.write(directory / "summary.json", CORE.verify(directory))
    CORE.write(directory / "manifest.json", {
        "started_utc": started, "finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "scope": "External live worker; resumed GET-only verification, no new load or mutations",
        "collection_resumed": True,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "verifier_sha256": hashlib.sha256(Path(SPEC.origin).read_bytes()).hexdigest(),
        "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(directory.iterdir()) if p.is_file()}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    resume(parser.parse_args().directory)
