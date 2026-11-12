#!/usr/bin/env python3
"""MET-07 preparation. Default CLI only prints a plan; no incident CLI is exposed."""
import argparse
import datetime as dt
import http.client
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import tempfile
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlencode, urlsplit

WORKER = "event-service-worker"
LABELS = {"app.kubernetes.io/name": "event-service", "app.kubernetes.io/component": "worker"}
SELECTOR = ",".join(f"{k}={v}" for k, v in sorted(LABELS.items()))
LIMIT = 600
GUARD_RESTORE = 540
LEASE = 30
RULE = "HighEventBacklog"
QUERY = "esc3_events_backlog_total > 100"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def utc(epoch):
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat()


def rule_state(body, namespace):
    require(body.get("status") == "success", "Prometheus query failed")
    rules = [r for g in body["data"]["groups"] for r in g["rules"] if r.get("name") == RULE]
    require(len(rules) == 1, "Missing or ambiguous HighEventBacklog rule")
    rule = rules[0]
    require(" ".join(rule["query"].split()) == QUERY and rule["duration"] == 120,
            "Rule must remain >100 for 2m")
    require(rule.get("health") == "ok" and not rule.get("lastError"), "Rule unhealthy")
    state = rule.get("state")
    require(state in ("inactive", "pending", "firing"), "Invalid alert state")
    if state == "firing":
        active = [a for a in rule.get("alerts", []) if a.get("state") == "firing"]
        require(active and all(a["labels"].get("job") == "event-service" and
                a["labels"].get("instance") == f"event-service.{namespace}.svc.cluster.local:8000"
                for a in active), "Firing alert belongs to another target")
    return state


def actor_identity():
    require(sys.platform == "linux", "Private IPC requires the reviewed Linux host")
    require(os.getuid() == os.geteuid() and os.getgid() == os.getegid(), "Mixed real/effective identity")
    return {"uid": os.geteuid(), "gid": os.getegid()}


def private_path(path, identity, directory=False, optional=False):
    """Check ownership even when root could otherwise bypass another user's permissions."""
    path = Path(path)
    require(isinstance(identity, dict) and set(identity) == {"uid", "gid"} and
            all(type(identity[k]) is int and identity[k] >= 0 for k in identity), "Invalid process identity")
    try:
        info = path.lstat()
    except FileNotFoundError:
        require(optional, "Required private IPC path missing")
        return
    require(not stat.S_ISLNK(info.st_mode), "Symlink forbidden in private IPC")
    require((info.st_uid, info.st_gid) == (identity["uid"], identity["gid"]), "Private IPC owner/group mismatch")
    require(stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600), "Private IPC permissions mismatch")
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), "Private IPC type mismatch")
    if not directory:
        require(info.st_nlink == 1, "Hard-linked IPC file forbidden")


def check_ipc(directory, identity):
    require(actor_identity() == identity, "Supervisor/watchdog identity mismatch")
    private_path(directory, identity, directory=True)
    # Same identity must actually create and read private files; atomic writers verify replacement.
    with tempfile.TemporaryFile(dir=directory) as probe:
        probe.write(b"met07-private-probe")
        probe.flush()
        probe.seek(0)
        require(probe.read() == b"met07-private-probe", "Private IPC access probe failed")


def read_private(path, identity):
    private_path(Path(path).parent, identity, directory=True)
    private_path(path, identity)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "r", encoding="utf8") as source:
        info = os.fstat(source.fileno())
        require((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink) ==
                (identity["uid"], identity["gid"], 0o600, 1), "Private IPC changed while opening")
        return json.load(source)


def server_instant(value):
    require(isinstance(value, str) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value),
        "Expected timezone-aware server timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RuntimeError("Invalid server timestamp") from error
    require(parsed.utcoffset() is not None, "Missing server timezone")
    return parsed.astimezone(dt.timezone.utc)


def attempt_associations(attempts, device, strict=True):
    starts, results = {}, {}
    for record in attempts:
        kind = record.get("kind")
        if kind not in ("attempt_started", "attempt_result"):
            continue
        number = record.get("attempt")
        require(type(number) is int and number >= 0, "Invalid attempt number")
        target = starts if kind == "attempt_started" else results
        require(number not in target, "Duplicate attempt record")
        target[number] = record
    require(starts, "No load evidence")
    require(set(results) <= set(starts), "Result without a started request")
    associations, events, unresolved = {}, {}, []
    for number, start in starts.items():
        require(start.get("device_id") == device and isinstance(start.get("event_id"), str) and
                bool(start["event_id"]), "Started request identity mismatch")
        result = results.get(number)
        if result is None:
            unresolved.append(number)
            continue
        require((result.get("device_id"), result.get("event_id")) == (device, start["event_id"]),
                "Response/request identity mismatch")
        if result.get("connection_error") or result.get("http_status") not in (200, 202) or not result.get("reading_id"):
            unresolved.append(number)
            continue
        rid = result["reading_id"]
        try:
            require(isinstance(rid, str) and str(uuid.UUID(rid)) == rid, "Invalid reading UUID")
        except (ValueError, AttributeError) as error:
            raise RuntimeError("Invalid reading UUID") from error
        require(not result.get("request_id") or not start.get("request_id") or
                result["request_id"] == start["request_id"], "Response request_id mismatch")
        pair = (device, start["event_id"])
        require(rid not in associations or associations[rid]["pair"] == pair, "UUID reused for another event")
        require(pair not in events or events[pair] == rid, "Idempotency ID mismatch")
        request_ids = set(associations.get(rid, {}).get("request_ids", []))
        request_id = result.get("request_id") or start.get("request_id")
        if request_id is not None:
            require(re.fullmatch(r"[A-Za-z0-9._-]{1,128}", request_id), "Invalid request_id")
            request_ids.add(request_id)
        associations[rid] = {"pair": pair, "request_ids": sorted(request_ids)}
        events[pair] = rid
    if strict:
        require(not unresolved and len(results) == len(starts), "Failed or unfinished request; outcome uncertain")
    return associations, unresolved


def processed(attempts, rows, device):
    associations, _ = attempt_associations(attempts, device)
    stored = {}
    for row in rows:
        rid = row.get("id")
        require(rid in associations and rid not in stored, "Unexpected or duplicate persisted UUID")
        require((row.get("device_id"), row.get("event_id")) == associations[rid]["pair"],
                "Persisted UUID/device/event does not match response")
        received = server_instant(row.get("received_at"))
        completed = server_instant(row.get("processed_at"))
        require(completed >= received, "Processing precedes durable reception")
        stored[rid] = row
    require(set(stored) == set(associations), "UUID set mismatch: responses versus durable rows")
    return sorted(stored)



def signal_manifest(events, rows, device):
    """Prepared instructions, never observations. All bounds originate in server timestamps."""
    processed(events, rows, device)
    boundaries = {e["phase"]: e["server_utc"] for e in events if e.get("kind") == "signal_phase_boundary"}
    samples = [e["data"]["server_utc"] for e in events if e.get("kind") == "snapshot"]
    require(set(boundaries) == {"before", "during", "after"} and samples, "Missing server phase boundaries")
    end = max(samples, key=server_instant)
    windows = {
        "before": {"start": boundaries["before"], "end": boundaries["during"]},
        "during": {"start": boundaries["during"], "end": boundaries["after"]},
        "after": {"start": boundaries["after"], "end": end},
    }
    for window in windows.values():
        require(server_instant(window["start"]) <= server_instant(window["end"]), "Reversed signal window")
    return {"material": "PREPARED_COLLECTION_PLAN", "observations_collected": False, "device_id": device,
            "windows": windows, "trace_margin_seconds": 60,
            "log_fields": ["server_utc", "reading_id", "trace_id", "span_id", "receipt_id", "request_id", "outcome"],
            "requires": "Follow API/worker logs before degradation; retain buffers across worker Pod deletion"}


def gaps(attempts, start, end, period=0.5):
    """Monotonic request-free intervals, including window boundaries; never interpolate load."""
    times = sorted(a["mono"] for a in attempts if a["kind"] == "attempt_started" and start <= a["mono"] <= end)
    points = [start, *times, end]
    return [{"from_mono": a, "to_mono": b, "seconds": b-a,
             "missed_schedule": b-a > period * 1.5}
            for a, b in zip(points, points[1:]) if b > a]


class Evidence:
    def __init__(self, directory, clock=time.monotonic):
        self.root = Path(directory).absolute()
        self.root.mkdir(mode=0o700)
        self.identity = actor_identity()
        check_ipc(self.root, self.identity)
        self.clock = clock
        self.lock = threading.Lock()
        self.records = []
        self.anchor = None

    def check_access(self):
        check_ipc(self.root, self.identity)

    def safe(self, value):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False)
        for key in ("EVENT_PRODUCER_KEY", "EVENT_ANALYST_KEY"):
            secret = os.environ.get(key)
            require(not secret or secret not in data, "Credential detected; refusing evidence")
        return data

    def json(self, name, value):
        self.check_access()
        require(Path(name).name == name, "Evidence filename required")
        data = self.safe(value)
        fd = os.open(self.root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf8") as out:
            out.write(data + "\n")
            out.flush()
            os.fsync(out.fileno())
        private_path(self.root / name, self.identity)

    def event(self, kind, **fields):
        record = {"kind": kind, "mono": self.clock(), "server_anchor": self.anchor, **fields}
        data = self.safe(record) + "\n"
        with self.lock:
            self.check_access()
            file = self.root / "events.jsonl"
            private_path(file, self.identity, optional=True)
            fd = os.open(file, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf8") as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
            private_path(file, self.identity)
            self.records.append(record)
        return record



class Http:
    def __init__(self, api="http://127.0.0.1:28000", prom="http://127.0.0.1:29090"):
        self.api, self.prom = api, prom

    def request(self, base, method, path, payload=None, role=None, request_id=None):
        url = urlsplit(base)
        require(url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost"),
                "Use an explicitly verified loopback forward")
        headers = {"Content-Type": "application/json"}
        if request_id:
            require(re.fullmatch(r"[A-Za-z0-9._-]{1,128}", request_id), "Invalid request_id")
            headers["X-Request-ID"] = request_id
        if role:
            headers["X-API-Key"] = os.environ["EVENT_" + role.upper() + "_KEY"]
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=2)
        try:
            conn.request(method, path, None if payload is None else json.dumps(payload), headers)
            response = conn.getresponse()  # No redirects followed, including with API keys.
            status, date = response.status, response.getheader("Date")
            try:
                raw = response.read()
            except (OSError, TimeoutError, http.client.HTTPException):
                return {"status": status, "server_date": date, "body": None,
                        "connection_error": "response_body_connection_or_timeout"}
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                body = None
            return {"status": status, "server_date": date, "body": body}
        finally:
            conn.close()

    def get(self, base, path, role=None):
        r = self.request(base, "GET", path, role=role)
        require(r["status"] == 200 and r["body"] is not None, "HTTP/read response failed")
        return r["body"]

    def query(self, expression):
        body = self.get(self.prom, "/api/v1/query?" + urlencode({"query": expression}))
        require(body.get("status") == "success", "Prometheus query error")
        return body["data"]

    def server_time(self):
        data = self.query("time()")
        require(data["resultType"] == "scalar", "Missing server time")
        value = float(data["result"][1])
        require(value > 0, "Invalid server time")
        return value

    def snapshot(self, namespace, device=None):
        server = self.server_time()
        server_sample_mono = time.monotonic()
        rules = self.get(self.prom, "/api/v1/rules")
        state = rule_state(rules, namespace)
        result = {"server_utc": utc(server), "server_epoch": server, "server_sample_mono": server_sample_mono, "alert_state": state,
                  "rule": {"query": QUERY, "duration": 120}, "metrics": {}}
        for name, query in {
            "backlog": 'esc3_events_backlog_total{job="event-service"}',
            "input_per_second": 'sum(rate(esc3_events_received_total{job="event-service",outcome="accepted"}[1m]))',
            "processed_per_second": 'sum(rate(esc3_events_processed_total{job="event-service-worker"}[1m]))',
            "http_5xx_per_second": 'sum(rate(http_requests_total{job="event-service",status=~"5.."}[1m]))',
            "http_p95_seconds": 'histogram_quantile(0.95,sum by(le)(rate(http_request_duration_seconds_bucket{job="event-service",route="/v1/readings"}[1m])))',
        }.items():
            result["metrics"][name] = self.query(query)  # Retain empty/NaN, never fill with zero.
        target = f"event-service.{namespace}.svc.cluster.local:8000"
        backlog = [s for s in result["metrics"]["backlog"]["result"] if s["metric"].get("instance") == target]
        require(len(backlog) == 1, "Missing/ambiguous backlog target")
        result["backlog"] = float(backlog[0]["value"][1])
        require(math.isfinite(result["backlog"]) and result["backlog"] >= 0, "Invalid backlog")
        path = "/v1/reception/counts" + ("?" + urlencode({"device_id": device}) if device else "")
        result["counts"] = self.get(self.api, path, "analyst")
        return result


class Kubernetes:
    def __init__(self, context, namespace, command=None):
        require(context and re.fullmatch(r"(eventos-development|met07-[a-z0-9-]+)", namespace),
                "Explicit approved context/test namespace required")
        self.context, self.namespace = context, namespace
        self.command = command or self._command

    @staticmethod
    def _command(args):
        r = subprocess.run(args, capture_output=True, text=True, timeout=5, check=False)
        require(r.returncode == 0, "Kubernetes command failed")
        return r.stdout

    def k(self, *args):
        return self.command(["sudo", "-n", "k3s", "kubectl", "--context", self.context,
                             "--namespace", self.namespace, "--request-timeout=3s", *args])

    def get(self):
        return json.loads(self.k("get", "deployment/" + WORKER, "-o", "json"))

    def preflight(self, expected_uid):
        current = self.command(["sudo", "-n", "k3s", "kubectl", "config", "current-context"]).strip()
        require(current == self.context, "Context mismatch")
        d = self.get()
        require(d["metadata"]["uid"] == expected_uid, "Deployment UID mismatch")
        require(d["spec"]["replicas"] == 1 and d["status"].get("readyReplicas") == 1 and
                d["status"].get("availableReplicas") == 1 and
                d["status"].get("observedGeneration", -1) >= d["metadata"]["generation"],
                "Exactly one ready worker required")
        require(d["spec"]["selector"]["matchLabels"] == LABELS, "Worker labels differ from reviewed selector")
        require(all(d["spec"]["template"]["metadata"]["labels"].get(k) == v for k, v in LABELS.items()),
                "Template label mismatch")
        containers = d["spec"]["template"]["spec"]["containers"]
        require(len(containers) == 1 and containers[0].get("args") == ["process"], "Not the process worker")
        for kind in ("deployment", "replicaset", "pod"):
            values = json.loads(self.k("get", kind, "-l", SELECTOR, "-o", "json"))["items"]
            if kind == "deployment":
                require(len(values) == 1 and values[0]["metadata"]["uid"] == expected_uid,
                        "Ambiguous worker deployment")
            elif kind == "replicaset":
                owners = {r["metadata"]["uid"] for r in values if any(
                    o.get("uid") == expected_uid and o.get("controller") for o in r["metadata"].get("ownerReferences", []))}
            else:
                require(len(values) == 1 and values[0]["status"]["phase"] == "Running" and any(
                    o.get("uid") in owners and o.get("controller") for o in values[0]["metadata"].get("ownerReferences", [])),
                    "Ambiguous/foreign worker pod")
        hpas = json.loads(self.k("get", "hpa", "-o", "json"))["items"]
        require(not any(h["spec"]["scaleTargetRef"]["name"] == WORKER for h in hpas), "HPA can undo the experiment")
        require(self.k("auth", "can-i", "patch", "deployments.apps").strip() == "yes", "Restore permission missing")
        return {"context": self.context, "namespace": self.namespace, "uid": expected_uid,
                "replicas": d["spec"]["replicas"], "selector": SELECTOR,
                "image": containers[0]["image"], "resource_version": d["metadata"]["resourceVersion"]}

    def scale(self, state, replicas):
        require(state["context"] == self.context and state["namespace"] == self.namespace, "Restore context mismatch")
        require(replicas in (0, state["replicas"]), "Only degradation or original replicas allowed")
        d = self.get()
        require(d["metadata"]["uid"] == state["uid"], "UID changed; never mutate replacement Deployment")
        current = d["spec"]["replicas"]
        require(current in (0, state["replicas"]), "Concurrent scaling detected")
        if replicas == 0:
            require(current == state["replicas"], "Already degraded by another actor")
        if current == replicas:
            return
        patch = [
            {"op": "test", "path": "/metadata/uid", "value": state["uid"]},
            {"op": "test", "path": "/metadata/resourceVersion", "value": d["metadata"]["resourceVersion"]},
            {"op": "test", "path": "/spec/replicas", "value": current},
            {"op": "replace", "path": "/spec/replicas", "value": replicas},
        ]
        self.k("patch", "deployment/" + WORKER, "--type=json", "-p", json.dumps(patch))

    def empty(self):
        return not json.loads(self.k("get", "pod", "-l", SELECTOR, "-o", "json"))["items"]

    def ready(self, state):
        d = self.get()
        return d["metadata"]["uid"] == state["uid"] and d["spec"]["replicas"] == state["replicas"] and (
            d["status"].get("readyReplicas") == state["replicas"] and
            d["status"].get("availableReplicas") == state["replicas"] and
            d["status"].get("observedGeneration", -1) >= d["metadata"]["generation"])


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def atomic_file(path, value, identity=None):
    path = Path(path)
    identity = actor_identity() if identity is None else identity
    require(actor_identity() == identity, "IPC writer identity mismatch")
    private_path(path.parent, identity, directory=True)
    private_path(path, identity, optional=True)
    temp = path.with_suffix(".tmp-" + uuid.uuid4().hex)
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf8") as out:
            json.dump(value, out)
            out.flush()
            os.fsync(out.fileno())
        private_path(temp, identity)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()



class RemoteGuard:
    """Independent remote systemd watchdog; never tied to a local SSH job."""
    def arm(self, state, directory):
        require(sys.platform == "linux" and Path("/run/systemd/system").exists(),
                "Run only on the reviewed remote systemd host")
        require(boot_id() == state["boot_id"], "Boot changed")
        self.directory = Path(directory)
        self.identity = state["identity"]
        check_ipc(self.directory, self.identity)
        require(read_private(self.directory / "restore-state.json", self.identity) == state, "Restore state mismatch")
        self.heartbeat()
        unit = "met07-guard-" + state["run"]
        subprocess.run(["sudo", "-n", "systemd-run", "--unit", unit, "--collect",
                        "--property=Restart=on-failure", "--property=RestartSec=1s",
                        "--property=User=" + str(self.identity["uid"]),
                        "--property=Group=" + str(self.identity["gid"]), "--property=UMask=0077",
                        "/usr/bin/python3", str(Path(__file__).resolve()), "watchdog",
                        "--state", str(self.directory / "restore-state.json")],
                       timeout=5, check=True, capture_output=True)
        for _ in range(20):
            if (self.directory / "guard-ready.json").exists():
                ready = read_private(self.directory / "guard-ready.json", self.identity)
                require(ready.get("identity") == self.identity, "Watchdog ACK identity mismatch")
                require(ready["run"] == state["run"] and ready["uid"] == state["uid"], "Foreign guard ACK")
                return
            time.sleep(0.25)
        raise RuntimeError("Remote guard did not acknowledge; do not degrade")

    def heartbeat(self):
        atomic_file(self.directory / "heartbeat.json", {"mono": time.monotonic()}, self.identity)

    def disarm(self):
        # Only after restoration is verified; watchdog also independently checks replicas.
        atomic_file(self.directory / "finished.json", {"restored": True}, self.identity)


def watchdog(state_file, clock=time.monotonic, sleep=time.sleep, kube=None, boot=None):
    state_file = Path(state_file)
    identity = actor_identity()
    check_ipc(state_file.parent, identity)
    state = read_private(state_file, identity)
    require(state.get("identity") == identity, "Watchdog process identity mismatch")
    private_path(state_file, state["identity"])
    require((boot or boot_id()) == state["boot_id"], "Boot changed; manual recovery required")
    require(state["deadline_mono"] - state["degraded_mono"] == LIMIT and state["replicas"] == 1,
            "Invalid restoration deadline/state")
    kube = kube or Kubernetes(state["context"], state["namespace"])
    directory = state_file.parent
    heartbeat_file = directory / "heartbeat.json"
    if heartbeat_file.exists():
        read_private(heartbeat_file, identity)
    atomic_file(directory / "guard-ready.json", {"run": state["run"], "uid": state["uid"], "identity": identity}, identity)
    while True:
        heartbeat = directory / "heartbeat.json"
        last = read_private(heartbeat, identity)["mono"] if heartbeat.exists() else state["degraded_mono"]
        reason = ("deadline" if clock() >= state["degraded_mono"] + GUARD_RESTORE else
                  "lost-supervisor" if clock() - last > LEASE else
                  "finished" if (directory / "finished.json").exists() else None)
        if reason:
            try:
                kube.scale(state, state["replicas"])
                require(kube.ready(state), "Restored replica not ready yet")
                atomic_file(directory / "guard-restored.json",
                            {"run": state["run"], "uid": state["uid"], "reason": reason, "mono": clock(),
                             "within_deadline": clock() <= state["deadline_mono"]})
                return
            except Exception:
                # Retrying continues independently of local SSH. Never claim restored on failure.
                atomic_file(directory / "guard-failure.json", {"reason": reason, "mono": clock(),
                            "deadline_exceeded": clock() >= state["deadline_mono"]})
        sleep(1)


class Experiment:
    """Dependency-injected supervisor. Invoking this API requires separate incident authorization."""
    def __init__(self, kube, http, guard, evidence, clock=time.monotonic, sleep=time.sleep, signals_factory=None):
        self.kube, self.http, self.guard, self.evidence = kube, http, guard, evidence
        self.clock, self.sleep = clock, sleep
        self.stop = threading.Event()
        self.load_stop = threading.Event()
        self.phase = "before"
        self.load_error = None
        self.load_deadline = float("inf")
        self.signals_factory, self.signals = signals_factory, None

    def sample(self, device=None):
        self.guard.heartbeat() if hasattr(self.guard, "directory") else None
        sample = self.http.snapshot(self.kube.namespace, device)
        self.evidence.anchor = {"server_utc": sample["server_utc"], "mono": sample["server_sample_mono"],
                                "source": "prometheus_time_scalar"}
        self.evidence.event("snapshot", phase=self.phase, data=sample)
        return sample

    def load(self, device):
        n, due = 0, self.clock()
        try:
            while not self.load_stop.is_set():
                require(n < 1200 and self.clock() < self.load_deadline, "Load safety bound reached")
                if self.clock() < due:
                    self.sleep(min(0.05, due - self.clock()))
                    continue
                event = f"e-{n}"
                request_id = str(uuid.uuid4())
                started = self.evidence.event("attempt_started", attempt=n, event_id=event, phase=self.phase,
                                              scheduled_mono=due, device_id=device, request_id=request_id)
                result = {"attempt": n, "event_id": event, "device_id": device, "request_id": request_id, "phase": self.phase,
                          "http_status": None, "connection_error": None, "reading_id": None,
                          "response_server_date": None, "start_mono": started["mono"]}
                try:
                    r = self.http.request(self.http.api, "POST", "/v1/readings",
                        {"device_id": device, "event_id": event, "occurred_at": "2040-01-01T00:00:00Z",
                         "temperature": 20, "humidity": 50, "state": "running"}, "producer", request_id=request_id)
                    result.update(http_status=r["status"], response_server_date=r["server_date"],
                                  connection_error=r.get("connection_error"))
                    if isinstance(r["body"], dict):
                        result["reading_id"] = r["body"].get("reading_id")
                    else:
                        result["connection_error"] = result["connection_error"] or "invalid_response"
                except (OSError, TimeoutError, http.client.HTTPException):
                    result["connection_error"] = "connection_or_timeout"
                finally:
                    self.evidence.event("attempt_result", **result)
                n += 1
                due += 0.5  # 2/s, including all degraded observation; lag remains visible.
                if self.clock() - due > 1:
                    self.evidence.event("schedule_lag", seconds=self.clock()-due)
                    due = self.clock()  # Do not compensate with an unreported burst.
        except BaseException:
            self.load_error = "load_recorder_failed"
            self.stop.set()

    def check(self, state):
        require(not self.stop.is_set() and not self.load_error, "Cancelled or load journal failed")
        require(self.clock() < state["degraded_mono"] + GUARD_RESTORE, "Safety deadline reached")
        require(not (self.evidence.root / "guard-restored.json").exists(), "Watchdog restored; incident not successful")
        self.guard.heartbeat()

    def restore(self, state):
        while True:
            try:
                self.kube.scale(state, state["replicas"])
                self.evidence.event("restore_requested", uid=state["uid"], replicas=state["replicas"],
                                    deadline_exceeded=self.clock() > state["deadline_mono"])
                return
            except Exception:
                self.evidence.event("restore_retry")
                require(self.clock() < state["deadline_mono"], "Restoration deadline exceeded; watchdog remains active")
                self.sleep(1)

    def run(self, authorization):
        require(authorization.get("incident_authorized") is True and authorization.get("isolated") is True and
                authorization.get("isolation_review_ref"), "Explicit authorization and isolation evidence required")
        require(authorization["context"] == self.kube.context and authorization["namespace"] == self.kube.namespace,
                "Authorization scope mismatch")
        self.evidence.check_access()
        state = self.kube.preflight(authorization["deployment_uid"])
        state["identity"] = self.evidence.identity
        before = self.sample()
        require(before["alert_state"] == "inactive" and before["backlog"] == 0, "Baseline must be inactive/zero")
        state.update(isolation_review_ref=authorization["isolation_review_ref"], server_before_utc=before["server_utc"])
        self.evidence.json("context.json", state)
        self.evidence.event("signal_phase_boundary", phase="before", server_utc=before["server_utc"])
        device = "met07-" + uuid.uuid4().hex
        created = self.http.request(self.http.api, "POST", "/v1/devices",
            {"id": device, "facility_id": "met07-isolated",
             "limits": {"temperature_min": 0, "temperature_max": 35, "humidity_min": 20, "humidity_max": 80}}, "producer")
        require(created["status"] == 201, "Device registration failed; do not retry blindly")
        self.evidence.event("device_registered", device_id=device, server_date=created["server_date"])
        thread = threading.Thread(target=self.load, args=(device,), daemon=True)
        degraded, restored, success, failure = False, False, False, None
        thread_started = False
        previous = {}
        try:
            if self.signals_factory is not None:
                self.signals = self.signals_factory(self.kube, self.http, state["uid"], device)
                self.signals.start_follow(before["server_utc"], self.evidence)
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                previous[sig] = signal.signal(sig, lambda *_: self.stop.set())
            thread.start()
            thread_started = True
            for _ in range(2):  # Ten seconds of observed baseline, with ongoing requests.
                require(not self.stop.is_set(), "Cancelled before degradation")
                self.sample(device)
                self.sleep(5)
            # Arm the independent guard BEFORE the first mutation. Its deadline starts no later than T2.
            state.update(run=uuid.uuid4().hex, device_id=device, boot_id=boot_id(),
                         degraded_mono=self.clock(), server_anchor=self.evidence.anchor)
            state["deadline_mono"] = state["degraded_mono"] + LIMIT
            self.load_deadline = state["deadline_mono"]
            self.evidence.json("restore-state.json", state)
            self.guard.arm(state, self.evidence.root)
            self.guard.heartbeat()
            self.check(state)
            self.evidence.event("signal_phase_boundary", phase="during", server_utc=utc(self.http.server_time()))
            degraded = True  # Even an uncertain scale result must enter restoration.
            self.phase = "during"
            self.evidence.event("degradation_started", state=state)
            self.kube.scale(state, 0)
            deletion_limit = self.clock() + 60
            while not self.kube.empty():
                self.check(state)
                require(self.clock() < deletion_limit, "Worker pods did not terminate")
                self.sleep(1)
            self.evidence.event("zero_worker_pods")
            while True:
                self.check(state)
                require(self.kube.get()["spec"]["replicas"] == 0, "Unexpected capacity restoration")
                current = self.sample(device)
                self.check(state)
                if current["alert_state"] == "firing":
                    self.evidence.event("firing_observed", server_utc=current["server_utc"])
                    break
                self.sleep(5)
            self.restore(state)  # Normal restoration requires actual Prometheus firing.
            restored = True
            while not self.kube.ready(state):
                self.check(state)
                self.sleep(1)
            self.check(state)
            self.evidence.event("worker_ready", uid=state["uid"])
            self.evidence.event("signal_phase_boundary", phase="after", server_utc=utc(self.http.server_time()))
            self.phase = "after"
            self.window_end = self.clock()
            self.evidence.event("degraded_window_ended")
            success = True
        except BaseException as error:
            failure = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        finally:
            self.load_stop.set()
            if thread_started:
                thread.join(timeout=3)
            if self.stop.is_set() or self.load_error:
                success, failure = False, "cancelled_or_load_failed"
            if degraded and not restored:
                try:
                    self.restore(state)
                    restored = True
                except BaseException:
                    failure = "restore_failed_watchdog_active"
            if restored:
                self.guard.disarm()
            if self.signals is not None:
                try:
                    self.signals.stop_follow()
                except Exception:
                    success, failure = False, "signal_stream_cleanup_failed"
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            self.evidence.json("request-free-intervals.json", {
                "period_seconds": 0.5, "intervals": gaps(self.evidence.records, state.get("degraded_mono", self.clock()),
                                                       self.clock()), "load_stop_mono": self.clock()})
            self.evidence.json("control-result.json", {"normal_firing_path": success,
                "restore_requested": restored, "failure": failure, "device_id": device})
        require(success and restored and not thread.is_alive(), "Control failed; collect watchdog evidence, do not claim success")
        # Verification continues after capacity restoration; never extend degradation for evidence.
        until = self.clock() + 180
        while True:
            sample = self.sample(device)
            require(self.clock() < until, "Recovery verification timeout")
            if self.kube.ready(state) and sample["alert_state"] == "inactive" and sample["backlog"] == 0 and sample["counts"]["pending"] == 0:
                break
            self.sleep(2)
        rows, offset = [], 0
        while True:
            page = self.http.get(self.http.api, "/v1/devices/" + device + "/readings?" + urlencode({
                "from": "2040-01-01T00:00:00Z", "to": "2041-01-01T00:00:00Z", "limit": 1000, "offset": offset}), "analyst")
            require(isinstance(page, list), "Invalid historical response")
            rows.extend(page)
            if len(page) < 1000:
                break
            offset += 1000
            require(offset < 10000, "Unexpected volume")
        self.evidence.json("after-readings.json", rows)
        acceptance = {"passed": False, "device_id": device, "backlog": 0, "alert_state": "inactive",
                      "scope": "functional_recovery_only", "logs_and_traces_collected": False}
        try:
            during = [a for a in self.evidence.records if a["kind"] == "attempt_started" and
                      state["degraded_mono"] <= a["mono"] <= self.window_end]
            require(during, "No observed load in degraded window")
            intervals = gaps(self.evidence.records, state["degraded_mono"], self.window_end)
            acceptance["load_coverage"] = {"during_attempts": len(during),
                "missed_schedule_intervals": sum(i["missed_schedule"] for i in intervals),
                "maximum_request_free_seconds": max((i["seconds"] for i in intervals), default=0)}
            acceptance["processed_ids"] = processed(self.evidence.records, rows, device)
            require(sample["counts"]["accepted"] == len(acceptance["processed_ids"]) and
                    sample["counts"]["processed"] == len(acceptance["processed_ids"]), "Ledger/UUID mismatch")
            plan = signal_manifest(self.evidence.records, rows, device)
            self.evidence.json("signal-collection-plan.json", plan)
            if self.signals is not None:
                for phase, window in plan["windows"].items():
                    self.signals.collect(phase, window, self.evidence.records, rows, self.evidence)
                acceptance.update(logs_and_traces_collected=True, signal_provenance=self.signals.mode,
                                  scope="functional_recovery_with_correlated_signals")
            acceptance["passed"] = True
        finally:
            self.evidence.json("acceptance.json", acceptance)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["plan", "watchdog"], nargs="?", default="plan")
    parser.add_argument("--state")
    args = parser.parse_args()
    if args.mode == "watchdog":
        require(args.state, "--state required")
        watchdog(args.state)
    else:
        print(json.dumps({"status": "PREPARED_NOT_EXECUTED", "issue": "Refs #27", "selector": SELECTOR,
                          "rule": QUERY, "for_seconds": 120, "maximum_degradation_seconds": LIMIT,
                          "watchdog_restoration_starts_seconds": GUARD_RESTORE,
                          "lost_supervisor_seconds": LEASE, "rate": 2, "execute_cli": False}, indent=2))


if __name__ == "__main__":
    main()
