#!/usr/bin/env python3
"""Run the compulsory P3 profiles, or verify their complete published HTTP evidence."""
import argparse
import contextlib
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import time
import urllib.parse
import urllib.request


PROFILES = {"burst": (1000, 0, 0, 20), "extra": (1000, 50, 50, 20),
            "sustained": (2400, 0, 0, 0)}
START = dt.datetime(2040, 1, 1, tzinfo=dt.timezone.utc)
WINDOW = {"from": "2040-01-01T00:00:00Z", "to": "2041-01-01T00:00:00Z"}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def instant(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def expected(count, late, seed):
    rows = {}
    for event, n in ([(f"e-{n}", n) for n in range(count)] +
                     [(f"late-{k}", late - 1 - k) for k in range(late)]):
        mixed = (n * 6364136223846793005 + seed) % (2 ** 64)
        rows[event] = {"occurred_at": START + dt.timedelta(seconds=n),
                       "temperature": 10 + mixed % 400 / 10,
                       "humidity": 30 + mixed % 600 / 10}
    return rows


def verify_profile(profile, report, evidence):
    count, duplicates, late, invalid = PROFILES[profile]
    require(report["profile"] == profile and report["seed"] == 3, "Profile/seed mismatch")
    require(report["passed"] is True, "Generator failed")
    require((report["unique_requested"], report["duplicates_requested"],
             report["late_requested"], report["invalid_requested"]) ==
            (count + late, duplicates, late, invalid), "Compulsory load changed")
    statuses = {"202": count + late}
    if duplicates:
        statuses["200"] = duplicates
    if invalid:
        statuses["422"] = invalid
    require(report["statuses"] == statuses, "Unexpected HTTP statuses")
    require(report["lost_accepted"] == report["uncertain_requests"] == 0, "Loss/uncertainty")
    if profile == "sustained":
        require(report["target_rate"] == 20 and 120 <= report["emission_seconds"] <= 121
                and report["schedule_lag_ms_max"] < 1000, "Sustained timing failed")
    before, after = evidence["before"], evidence["after"]
    mode = evidence.get("processing_mode", "controlled-drain")
    require(mode in ("controlled-drain", "live-worker"), "Unknown processing mode")
    live = mode == "live-worker"
    require(evidence["window"] == WINDOW, "Unexpected query window")
    wanted = expected(count, late, 3)
    rows = after["readings"]
    require(len(rows) == len(wanted), "Historical count mismatch")
    require(len({r["id"] for r in rows}) == len(rows), "Repeated reading UUID")
    require({r["event_id"] for r in rows} == set(wanted), "Missing/unexpected event")
    require(rows == sorted(rows, key=lambda r: (instant(r["occurred_at"]), r["id"])),
            "Historical ordering failed across pages")
    for row in rows:
        target = wanted[row["event_id"]]
        require(row["device_id"] == report["device_id"] and row["state"] == "running"
                and instant(row["occurred_at"]) == target["occurred_at"]
                and row["temperature"] == target["temperature"]
                and row["humidity"] == target["humidity"] and row["processed_at"] is not None,
                "Persisted payload/processing mismatch")
    require(len(before["readings"]) == len(rows) and
            all((r["processed_at"] is not None) if live else (r["processed_at"] is None)
                for r in before["readings"]), "Unexpected initial processing state")
    require([{k: v for k, v in r.items() if k != "processed_at"} for r in before["readings"]] ==
            [{k: v for k, v in r.items() if k != "processed_at"} for r in rows], "Drain changed payload")
    for snapshot, processed in ((before, len(wanted) if live else 0), (after, len(wanted))):
        counters = snapshot["counters"]
        # Five invalid requests use a different, unknown device and are excluded by this filter.
        rejected = invalid - (invalid + 1) // 4
        require(counters == {"received": len(wanted) + duplicates + rejected,
                "validated": len(wanted) + duplicates, "accepted": len(wanted),
                "duplicates": duplicates, "rejected": rejected, "processed": processed,
                "pending": len(wanted) - processed}, "Counters do not conserve readings")
        require(snapshot["statistics"]["count"] == processed, "Statistics count mismatch")
    initial = report["counters"]
    require(initial["accepted"] == initial["processed"] + initial["pending"] and
            initial["processed"] >= 0 and initial["pending"] >= 0, "Initial processing counters invalid")
    require(all(initial[k] == before["counters"][k] for k in initial
                if not live or k not in ("processed", "pending")), "Generator/snapshot counters differ")
    if live:
        require(before["statistics"] == after["statistics"], "Settled aggregates changed")
    else:
        require(all(v is None for k, v in before["statistics"].items() if k != "count"),
                "Pending events contributed to aggregates")
    for field in ("temperature", "humidity"):
        values = [r[field] for r in wanted.values()]
        for suffix, value in (("min", min(values)), ("max", max(values)),
                              ("avg", sum(values) / len(values))):
            require(math.isclose(after["statistics"][f"{field}_{suffix}"], value,
                                 rel_tol=1e-10, abs_tol=1e-10), "Aggregate distortion")
    receipts = evidence["receipts"]
    require(len(receipts) == count + late + duplicates + invalid and
            [r["id"] for r in receipts] == report["receipt_ids"] and
            len({r["id"] for r in receipts}) == len(receipts), "Incomplete receipt ledger")
    for outcome, total in (("accepted", count + late), ("duplicate", duplicates), ("rejected", invalid)):
        require(sum(r["outcome"] == outcome for r in receipts) == total, "Receipt outcomes differ")
    ids = {r["id"] for r in rows}
    require(all(r["device_id"] == report["device_id"] for r in receipts
                if r["outcome"] in ("accepted", "duplicate")), "Receipt device does not match reading device")
    require({r["reading_id"] for r in receipts if r["outcome"] == "accepted"} == ids,
            "Accepted UUIDs differ from durable history")
    original = {r["id"] for r in rows if r["event_id"] in {f"e-{n}" for n in range(duplicates)}}
    require({r["reading_id"] for r in receipts if r["outcome"] == "duplicate"} == original,
            "Duplicates do not reference original readings")
    if late:
        delayed = [r for r in rows if r["event_id"].startswith("late-")]
        regular = [r for r in rows if r["event_id"].startswith("e-")]
        require(min(instant(r["received_at"]) for r in delayed) >
                max(instant(r["received_at"]) for r in regular), "No proof of late arrival")
        require([r["event_id"] for r in sorted(delayed, key=lambda r: instant(r["received_at"]))] ==
                [f"late-{n}" for n in range(late)], "Late events not submitted in reverse time order")
    window = evidence["half_open"]
    selected = [r for r in rows if START <= instant(r["occurred_at"]) < START + dt.timedelta(seconds=50)]
    require(window["readings"] == selected and window["statistics"]["count"] == len(selected),
            "[from,to) query mismatch")
    for field in ("temperature", "humidity"):
        values = [r[field] for r in selected]
        for suffix, value in (("min", min(values)), ("max", max(values)), ("avg", sum(values) / len(values))):
            require(math.isclose(window["statistics"][f"{field}_{suffix}"], value,
                                 rel_tol=1e-10, abs_tol=1e-10), "Window aggregate mismatch")
    return {"passed": True, "accepted": len(rows), "duplicates": duplicates, "late": late,
            "pending_before": initial["pending"], "pending_after": after["counters"]["pending"],
            "emission_seconds": report["emission_seconds"], "lost_accepted": 0}


def verify(directory):
    results = {}
    for profile in PROFILES:
        results[profile] = verify_profile(profile,
            json.loads((directory / f"{profile}-load.json").read_text()),
            json.loads((directory / f"{profile}-queries.json").read_text()))
    return results


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate_database_url(value):
    database = urllib.parse.urlparse(value)
    name = urllib.parse.unquote(database.path.lstrip("/"))
    require(database.scheme in ("postgres", "postgresql") and not database.fragment and
            database.hostname in ("localhost", "127.0.0.1") and
            (name.startswith("test_") or name.endswith("_test")), "Dedicated local test DB required")
    overrides = {key.lower() for key, _ in urllib.parse.parse_qsl(database.query, keep_blank_values=True)}
    require(not overrides & {"host", "hostaddr", "dbname", "port"},
            "DATABASE_URL must not override its host, hostaddr, dbname or port in the query")


def run(directory, external=False):
    require(not directory.exists(), "Output directory must be new; do not overwrite evidence")
    if not external:
        validate_database_url(os.environ["DATABASE_URL"])
    # This runner owns only its API process, never an existing worker, deployment or database.
    bind = os.environ.get("BIND_ADDR", "127.0.0.1:18083")
    require(bind.startswith("127.0.0.1:"), "Loopback bind required")
    base = os.environ["ESC3_BASE_URL"].rstrip("/") if external else f"http://{bind}"
    endpoint = urllib.parse.urlparse(base)
    require(endpoint.scheme in ("http", "https") and endpoint.hostname in ("localhost", "127.0.0.1")
            and not endpoint.username and not endpoint.password and not endpoint.query
            and not endpoint.fragment and endpoint.path in ("", "/"), "Loopback API/tunnel required")
    env = {**os.environ, "BIND_ADDR": bind, "ESC3_BASE_URL": base}
    directory.mkdir(parents=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def get(path):
        request = urllib.request.Request(base + path, headers={"X-API-Key": env["EVENT_ANALYST_KEY"]})
        with opener.open(request, timeout=10) as response:
            return json.load(response)

    def readings(device, window):
        result = []
        for offset in range(0, 10000, 1000):
            page = get(f"/v1/devices/{device}/readings?" +
                       urllib.parse.urlencode({**window, "limit": 1000, "offset": offset}))
            result.extend(page)
            if len(page) < 1000:
                return result
        raise RuntimeError("Pagination exceeded bounded profile")

    def snapshot(device, window=WINDOW):
        return {"readings": readings(device, window),
                "statistics": get(f"/v1/devices/{device}/statistics?" + urllib.parse.urlencode(window)),
                "counters": get("/v1/reception/counts?" + urllib.parse.urlencode({"device_id": device}))}

    started = dt.datetime.now(dt.timezone.utc).isoformat()
    if not external:
        with (directory / "migrate.log").open("w") as log:
            subprocess.run(["target/debug/event-service", "migrate"], env=env, stdout=log, stderr=log, check=True)
    with (contextlib.nullcontext(None) if external else (directory / "api.log").open("w")) as log:
        api = None if external else subprocess.Popen(
            ["target/debug/event-service", "serve"], env=env, stdout=log, stderr=log)
        try:
            for _ in range(100):
                require(api is None or api.poll() is None, "Owned API exited; check api.log (port collision?)")
                try:
                    get("/health/ready")
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("API did not become ready")
            for profile in PROFILES:
                with (directory / f"{profile}-load.json").open("w") as out:
                    subprocess.run(["target/debug/examples/scenario_load", profile, "--seed", "3"],
                                   env=env, stdout=out, check=True)
                report = json.loads((directory / f"{profile}-load.json").read_text())
                device = report["device_id"]
                if external:
                    # Observe the existing worker; never scale/stop it or execute drain on the cluster.
                    deadline = time.monotonic() + 180
                    while True:
                        counters = get("/v1/reception/counts?" + urllib.parse.urlencode({"device_id": device}))
                        if counters["pending"] == 0 and counters["processed"] == report["unique_requested"]:
                            break
                        require(time.monotonic() < deadline, "Live worker did not settle within observation timeout")
                        time.sleep(0.5)
                evidence = {"window": WINDOW, "before": snapshot(device)}
                if external:
                    evidence["processing_mode"] = "live-worker"
                else:
                    with (directory / f"{profile}-drain.log").open("w") as drain:
                        subprocess.run(["target/debug/event-service", "drain"], env=env,
                                       stdout=drain, stderr=drain, check=True)
                evidence["after"] = snapshot(device)
                with ThreadPoolExecutor(max_workers=8) as readers:
                    evidence["receipts"] = list(readers.map(
                        lambda rid: get(f"/v1/receipts/{rid}"), report["receipt_ids"]))
                evidence["half_open"] = snapshot(device, {**WINDOW, "to": "2040-01-01T00:00:50Z"})
                write(directory / f"{profile}-queries.json", evidence)
                verify_profile(profile, report, evidence)
                print(f"PASS {profile}", flush=True)
        finally:
            if api is not None:
                api.terminate()
                try:
                    api.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    api.kill()
                    api.wait()
    write(directory / "summary.json", verify(directory))
    write(directory / "manifest.json", {
        "started_utc": started, "finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "platform": platform.platform(), "rust": subprocess.check_output(["rustc", "--version"], text=True).strip(),
        "scope": ("external API through loopback tunnel; existing live worker; no migration/drain/deployment changes"
                  if external else "isolated loopback API and PostgreSQL; not Azure/K3s"),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "github_run_url": (f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
                           if "GITHUB_RUN_ID" in os.environ else None),
        "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.iterdir())}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--verify", action="store_true", help="Offline verification, no DB/API needed")
    parser.add_argument("--external", action="store_true", help="Existing API via loopback tunnel; observe worker, never migrate/drain")
    args = parser.parse_args()
    if args.verify:
        manifest = json.loads((args.directory / "manifest.json").read_text())
        required = {f"{p}-{suffix}.json" for p in PROFILES for suffix in ("load", "queries")}
        require(required <= manifest["sha256"].keys(), "Incomplete manifest")
        for name, digest in manifest["sha256"].items():
            require(Path(name).name == name, "Unsafe manifest path")
            require(hashlib.sha256((args.directory / name).read_bytes()).hexdigest() == digest, "Hash mismatch")
        results = verify(args.directory)
        require(results == json.loads((args.directory / "summary.json").read_text()), "Summary mismatch")
        print(json.dumps(results, indent=2))
    else:
        run(args.directory, external=args.external)


if __name__ == "__main__":
    main()
