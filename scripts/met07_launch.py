"""One-shot Linux MET-07 launcher with server-clock window and VM-owned forwards."""
import datetime as dt
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import met07 as core
import met07_operate as op

START = '2026-11-12T21:00:00Z'
END = '2026-11-12T23:00:00Z'
UID = 'f1c9cafa-7fe9-4495-b806-94776f8a8326'
REPO = 'https://api.github.com/repos/marchelo23/Proyecto-Final-Metricas-y-DevOps'
POWER_WORKFLOW_ID = 411281561
POWER_RUNS = REPO + '/actions/workflows/411281561/runs'
MAX_WORKFLOW_PAGES = 10


def window(now=None, margin=True):
    now = time.time() if now is None else now
    start, end = (core.server_instant(value).timestamp() for value in (START, END))
    core.require(start <= now < end, 'Server clock outside authorized window')
    core.require(not margin or end - now > 1200, 'Must have more than 20 minutes remaining')
    return {'server_utc': core.utc(now), 'start': START, 'end': END, 'remaining_seconds': end - now}


def workflow_review(reader=op.read_url):
    """Only the named power workflow can contribute to power activity."""
    active, seen, total, pages = [], set(), None, []
    for page in range(1, MAX_WORKFLOW_PAGES + 1):
        response = reader(POWER_RUNS + '?per_page=100&page=' + str(page))
        core.require(response.get('http_status') == 200 and not response.get('connection_error'),
                     'Power workflow query failed')
        body = response.get('body')
        core.require(isinstance(body, dict) and isinstance(body.get('workflow_runs'), list) and
                     type(body.get('total_count')) is int and body['total_count'] >= 0,
                     'Invalid power workflow response')
        if total is None:
            total = body['total_count']
        core.require(total == body['total_count'], 'Power workflow inventory changed during pagination')
        rows = body['workflow_runs']
        core.require(len(rows) <= 100, 'Oversized power workflow page')
        for row in rows:
            core.require(isinstance(row, dict) and type(row.get('id')) is int and row['id'] > 0 and
                         type(row.get('workflow_id')) is int and row['workflow_id'] == POWER_WORKFLOW_ID and
                         isinstance(row.get('status'), str) and bool(row['status'].strip()),
                         'Invalid or foreign power workflow run')
            core.require(row['id'] not in seen, 'Duplicate power workflow run; pagination incomplete')
            seen.add(row['id'])
            if row['status'] != 'completed':
                active.append({key: row.get(key) for key in
                               ('id', 'workflow_id', 'name', 'status', 'event', 'head_branch', 'created_at')})
        pages.append({'page': page, 'http_status': response['http_status'], 'rows': len(rows)})
        core.require(len(seen) <= total, 'Power workflow count inconsistent')
        if len(seen) == total:
            return {'endpoint': POWER_RUNS, 'workflow_id': POWER_WORKFLOW_ID, 'total_count': total,
                    'pages': pages, 'inventory_complete': True, 'active': active}
        core.require(len(rows) == 100, 'Power workflow pagination incomplete')
    raise RuntimeError('Power workflow pagination incomplete; page limit reached')


class Forwards:
    PORTS = (('event-service', 28000, 8000), ('prometheus', 29090, 9090),
             ('jaeger-collector', 26686, 16686), ('grafana', 23000, 3000))

    def __init__(self, root, evidence):
        self.root, self.evidence, self.children = Path(root), evidence, []

    def start(self):
        for service, local, target in self.PORTS:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', local))
            log = (self.root / (service + '-forward.log')).open('x')
            args = ['sudo', '-n', 'k3s', 'kubectl', '--context', 'default', '--namespace', 'eventos-development',
                    '--request-timeout=3s', 'port-forward', '--address=127.0.0.1', 'service/' + service,
                    str(local) + ':' + str(target)]
            child = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            self.children.append((service, local, child, log))
        until = time.monotonic() + 15
        while True:
            self.verify()
            ready = True
            for _, port, _, _ in self.children:
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.2):
                        pass
                except OSError:
                    ready = False
            if ready:
                break
            core.require(time.monotonic() < until, 'Forward readiness timed out')
            time.sleep(.2)
        self.evidence.event('four_vm_forwards_started', services=[{'service': s, 'port': p, 'pid': c.pid} for s, p, c, _ in self.children])

    def verify(self):
        core.require(len(self.children) == 4 and all(child.poll() is None for _, _, child, _ in self.children),
                     'All four VM forwards must remain alive')

    def close(self):
        for _, _, child, log in self.children:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
            log.close()
        self.evidence.event('four_vm_forwards_stopped', all_stopped=all(c.poll() is not None for _, _, c, _ in self.children))


class LiveHttp(core.Http):
    def __init__(self, forwards):
        super().__init__()
        self.forwards = forwards

    def request(self, *args, **kwargs):
        self.forwards.verify()
        if len(args) > 1 and args[1] == 'POST':
            window(margin=args[2] == '/v1/devices')
        return super().request(*args, **kwargs)


class Launch:
    def __init__(self, payload, root):
        self.payload, self.root = payload, Path(root)
        self.evidence = core.Evidence(self.root / 'evidence')
        self.kube = core.Kubernetes('default', 'eventos-development')
        self.forwards = Forwards(self.root, self.evidence)
        self.http = LiveHttp(self.forwards)
        self.counter, self.last_review_mono = 0, None
        self.experiment, self.collector = None, None

    def preflight(self):
        gate = window()
        self.forwards.verify()
        state = self.kube.preflight(UID)
        workflows = workflow_review()
        now = dt.datetime.now(dt.timezone.utc)
        next_stop = now.replace(hour=5, minute=0, second=0, microsecond=0)
        if next_stop <= now:
            next_stop += dt.timedelta(days=1)
        external = {'checked_server_utc': core.utc(time.time()), 'next_stop_utc': next_stop.isoformat(),
                    'azure_schedules_verified': False, 'arm_query_performed': False,
                    'administrator_confirmation': self.payload['administrator_confirmation'],
                    'active_power_workflows': len(workflows['active']), 'workflow_review': workflows}
        power = op.power_check(external, time.time())
        endpoints = op.endpoint_checks(self.http)
        self.counter += 1
        self.evidence.json('preflight-' + str(self.counter) + '.json',
                           {'window': gate, 'worker': state, 'power': power, 'endpoints': endpoints})
        core.require(power['passed'], 'Power/workflow/administrative precondition failed')
        core.require(endpoints['passed'], 'Endpoint/credential precondition failed')
        window()
        self.last_review_mono = time.monotonic()
        return state

    def run(self):
        e = self.evidence
        confirmation = self.payload['administrator_confirmation']
        authorization = self.payload['authorization']
        core.require(self.payload.get('execute_once') is True and authorization.get('incident_authorized') is True and
                     authorization.get('isolated') is True and authorization.get('isolation_review_ref') and
                     authorization.get('context') == 'default' and authorization.get('namespace') == 'eventos-development' and
                     authorization.get('deployment_uid') == UID, 'Explicit one-shot authorization scope required')
        e.json('administrator-confirmation.json', confirmation)
        core.require(confirmation.get('window_start') == START and confirmation.get('window_end') == END,
                     'Administrative window differs from authorized window')
        e.json('invocation.json', {'authorization': self.payload['authorization'], 'material': 'REAL_OPERATIONAL_LAUNCH',
                                  'window': {'start': START, 'end': END}, 'automatic_incident_retry': False,
                                  'sources': self.payload['source_sha256']})
        # Waiting uses the Linux server clock; no forwards, guard, device or load before the window.
        start = core.server_instant(START).timestamp()
        core.require(op.administrative_window_clearance(confirmation, start), 'Invalid administrative evidence')
        while time.time() < start:
            remaining = start - time.time()
            print(json.dumps({'phase': 'waiting_authorized_window', 'server_utc': core.utc(time.time()),
                              'seconds_until_start': remaining}), flush=True)
            time.sleep(min(30, remaining))
        window()
        for name in ('EVENT_PRODUCER_KEY', 'EVENT_ANALYST_KEY'):
            core.require(bool(self.payload.get(name)), 'Credential absent')
            os.environ[name] = self.payload.pop(name)
        try:
            self.forwards.start()
            state = self.preflight()
            before = self.http.snapshot(self.kube.namespace)
            e.json('baseline.json', before)
            core.require(before['backlog'] == 0 and before['alert_state'] == 'inactive', 'Baseline not zero/inactive')
            ready = op.VerifiedCollector(self.kube, self.http, UID, 'met07-readiness-only', mode='real-read-only')
            try:
                ready.start_follow(before['server_utc'], e)
                ready.verify_live()
            finally:
                ready.stop_follow()
            # Real operational launcher and backend, with worker still 1/1; lease is allowed to expire.
            self.preflight()
            window()
            op.guard_probe(self.kube, state, e.root, self.http)
            self.preflight()
            before = self.http.snapshot(self.kube.namespace)
            e.json('post-guard-baseline.json', before)
            core.require(before['backlog'] == 0 and before['alert_state'] == 'inactive', 'Baseline changed after guard probe')
            launcher = self

            class Guard(op.CheckedGuard):
                def arm(self, restore_state, directory):
                    launcher.preflight()
                    launcher.collector.verify_live()
                    window()
                    super().arm(restore_state, directory)

            class IncidentKubernetes(core.Kubernetes):
                def scale(self, restore_state, replicas):
                    if replicas == 0:
                        window()
                        launcher.forwards.verify()
                        launcher.collector.verify_live()
                        core.require(launcher.last_review_mono is not None and
                                     time.monotonic() - launcher.last_review_mono < 30, 'Preflight became stale before degradation')
                        self.preflight(UID)
                        core.require(not (launcher.experiment.evidence.root / 'guard-restored.json').exists(),
                                     'Guard already restored; no degradation')
                    return super().scale(restore_state, replicas)

            def factory(kube, http, uid, device):
                self.collector = op.VerifiedCollector(kube, http, uid, device, mode='real-read-only')
                return self.collector

            window()
            with (self.root / 'incident-entry-claimed.json').open('x') as claim:
                json.dump({'server_utc': core.utc(time.time()), 'attempt': 1, 'automatic_retry': False}, claim)
            incident = core.Evidence(e.root / 'incident')
            self.experiment = core.Experiment(IncidentKubernetes('default', 'eventos-development'), self.http,
                                             Guard(lambda: self.collector), incident, signals_factory=factory)
            e.event('single_incident_entered', window=window())
            print(json.dumps({'phase': 'single_incident_entered', 'server_utc': core.utc(time.time())}), flush=True)
            self.experiment.run(self.payload['authorization'])
            e.json('result.json', {'passed': True, 'incident_entered': True, 'automatic_retry': False})
        except BaseException as error:
            e.json('launch-failure.json', {'type': type(error).__name__,
                                         'reason': str(error) if isinstance(error, RuntimeError) else 'operation_failed',
                                         'incident_entered': self.experiment is not None, 'automatic_retry': False})
            raise
        finally:
            try:
                # Keep forwards until recovery verification; guard uses K3s locally and survives this process.
                if self.experiment is not None and (self.experiment.evidence.root / 'restore-state.json').exists():
                    state = core.read_private(self.experiment.evidence.root / 'restore-state.json', e.identity)
                    until = time.monotonic() + 60
                    while not self.kube.ready(state):
                        try:
                            self.kube.scale(state, state['replicas'])
                        except RuntimeError:
                            e.event('recovery_request_failed')
                        if time.monotonic() >= until:
                            e.event('recovery_not_verified_watchdog_retained')
                            break
                        time.sleep(1)
                    e.json('recovery-state.json', {'worker_ready': self.kube.ready(state), 'server_utc': core.utc(time.time())})
                final = self.kube.get()
                e.json('final-worker.json', {'server_utc': core.utc(time.time()), 'uid': final['metadata']['uid'],
                                           'replicas': final['spec']['replicas'], 'ready': final['status'].get('readyReplicas'),
                                           'available': final['status'].get('availableReplicas')})
                if len(self.forwards.children) == 4 and all(c.poll() is None for _, _, c, _ in self.forwards.children):
                    try:
                        e.json('final-snapshot.json', self.http.snapshot(self.kube.namespace))
                    except Exception:
                        e.event('final_snapshot_unavailable')
            finally:
                self.forwards.close()



if __name__ == '__main__':
    os.umask(0o077)
    payload = json.load(sys.stdin)
    try:
        Launch(payload, Path(sys.argv[1])).run()
    except BaseException:
        print(json.dumps({'phase': 'failed_no_automatic_retry', 'server_utc': core.utc(time.time())}), flush=True)
        sys.exit(1)
