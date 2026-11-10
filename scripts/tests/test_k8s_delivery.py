"""Run deployment scripts against local doubles; no cluster, cloud or secrets needed."""

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
IMAGE = "ghcr.io/marchelo23/proyecto-final-metricas-y-devops/event-service@sha256:" + "1" * 64


class DeliveryTests(unittest.TestCase):
    """Exercise the actual shell scripts, not copies of their success conditions."""

    def executable(self, path, content):
        """Write a command double inside a test-owned temporary directory."""
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def test_smoke_requires_processing_of_the_exact_event(self):
        """Another processed reading must never satisfy the newly submitted event."""
        for processed in (False, True):
            with self.subTest(processed=processed), tempfile.TemporaryDirectory() as directory:
                work = Path(directory)
                self.executable(work / "kubectl", "#!/bin/sh\ncase \"$*\" in *get*secret*) echo dummy-key;; esac\n")
                self.executable(work / "sleep", "#!/bin/sh\nexit 0\n")
                self.executable(work / "curl", '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
url = args[-1]
body = pathlib.Path(args[args.index('--output') + 1])
state = pathlib.Path(os.environ['MOCK_STATE'])
headers = sys.stdin.read()
code, response = 200, {}
if '/health/' in url:
    pass
elif url.endswith('/v1/devices') and not headers:
    code = 401
elif '/readings?' in url:
    event = state.read_text()
    response = [{'event_id': event, 'processed_at': 'now' if os.environ['PROCESSED'] == '1' else None},
                {'event_id': 'previous-event', 'processed_at': 'earlier'}]
elif url.endswith('/v1/readings'):
    state.write_text(json.loads(args[args.index('--data') + 1])['event_id'])
    code = 202
body.write_text(json.dumps(response, separators=(',', ':')))
print(code, end='')
''')
                env = dict(os.environ, PATH=f"{work}:{os.environ['PATH']}",
                           KUBECTL=str(work / "kubectl"), MOCK_STATE=str(work / "event"),
                           PROCESSED="1" if processed else "0")
                result = subprocess.run(["bash", str(ROOT / "scripts/k8s-smoke.sh"), "development"],
                                        env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0 if processed else 1, result.stderr)
                self.assertEqual("SMOKE OK" in result.stdout, processed)

    def test_smoke_refuses_a_port_already_in_use(self):
        """A listener left on the port must not answer for the environment under test."""
        with tempfile.TemporaryDirectory() as directory, socket.socket() as listener:
            work = Path(directory)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            self.executable(work / "kubectl", '#!/bin/sh\ntouch "$MOCK_CALLED"\n')
            env = dict(os.environ, KUBECTL=str(work / "kubectl"), MOCK_CALLED=str(work / "called"),
                       SMOKE_PORT=str(listener.getsockname()[1]))
            result = subprocess.run(["bash", str(ROOT / "scripts/k8s-smoke.sh"), "production"],
                                    env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("ya está en uso", result.stderr)
            self.assertFalse((work / "called").exists())

    def test_smoke_closes_its_port_forward(self):
        """The tunnel must end with the script so the next environment can use the port."""
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            pid_file = work / "pid"
            self.executable(work / "kubectl", '''#!/bin/sh
case "$*" in
  *port-forward*) echo $$ >"$MOCK_PID.tmp"; mv "$MOCK_PID.tmp" "$MOCK_PID"; exec python3 -c 'import time; time.sleep(30)' ;;
esac
''')
            self.executable(work / "sleep", "#!/bin/sh\nexit 0\n")
            self.executable(work / "curl", '#!/bin/sh\nwhile [ ! -s "$MOCK_PID" ]; do :; done\nprintf 500\n')
            env = dict(os.environ, PATH=f"{work}:{os.environ['PATH']}", KUBECTL=str(work / "kubectl"),
                       MOCK_PID=str(pid_file))
            result = subprocess.run(["bash", str(ROOT / "scripts/k8s-smoke.sh"), "development"],
                                    env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 1, result.stderr)
            pid = int(pid_file.read_text())
            try:
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
            finally:
                try:
                    os.kill(pid, 9)
                except ProcessLookupError:
                    pass

    def test_partial_apply_restores_templates_with_stale_revision_annotations(self):
        """Restore changed templates immediately, leaving an unchanged worker untouched."""
        for both in (False, True):
            with self.subTest(both=both), tempfile.TemporaryDirectory() as directory:
                work = Path(directory)
                shutil.copyfile(ROOT / "scripts/k8s-deliver.sh", work / "k8s-deliver.sh")
                self.executable(work / "k8s-smoke.sh", "#!/bin/sh\necho 'SMOKE OK'\n")
                original = {name: {"metadata": {"annotations": {"deployment.kubernetes.io/revision": "7"}},
                                   "spec": {"template": {"metadata": {"labels": {"component": name}},
                                                         "spec": {"containers": [{"name": name, "image": IMAGE}]}}}}
                            for name in ("api", "worker")}
                state = work / "state.json"
                state.write_text(json.dumps({"deployments": original, "patched": []}))
                (work / "migration.json").write_text('event-service-migrate-' + '2' * 16)
                (work / "workloads.json").write_text('{}')
                self.executable(work / "kubectl", '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
state = pathlib.Path(os.environ['MOCK_STATE'])
data = json.loads(state.read_text())
op = next(value for value in args if value in ('get', 'apply', 'wait', 'patch', 'rollout'))
if op == 'get':
    resource = args[args.index(op) + 1]
    if resource == 'deployment':
        component = args[args.index(op) + 2].removeprefix('event-service-')
        output = args[args.index('-o') + 1]
        if output.startswith('jsonpath='):
            print('7' if 'revision' in output else os.environ['OLD_IMAGE'])
        else:
            print(json.dumps(data['deployments'][component]))
    elif resource == 'job':
        print('Complete')
    elif resource == 'pods':
        component = args[args.index('-l') + 1].split('=')[-1]
        print(data['deployments'][component]['spec']['template']['spec']['containers'][0]['image'])
    else:
        sys.exit('Unexpected resource: ' + resource)
elif op == 'apply' and args[-1].endswith('workloads.json') and '--dry-run=server' not in args:
    for component in ('api', 'worker') if os.environ['BOTH'] == '1' else ('api',):
        template = data['deployments'][component]['spec']['template']
        template['spec']['containers'][0]['image'] = 'broken-image'
        template['spec']['containers'][0]['env'] = [{'name': 'BIND_ADDR', 'value': 'invalid'}]
        # Deliberately leave deployment.kubernetes.io/revision unchanged.
    state.write_text(json.dumps(data))
    sys.exit(1)
elif op == 'patch':
    component = args[args.index(op) + 1].split('event-service-')[-1]
    patch = json.load(sys.stdin)
    assert patch[0]['op'] == 'replace' and patch[0]['path'] == '/spec/template'
    data['deployments'][component]['spec']['template'] = patch[0]['value']
    data['patched'].append(component)
    state.write_text(json.dumps(data))
elif op not in ('apply', 'wait', 'rollout'):
    sys.exit('Unexpected operation: ' + op)
''')
                env = dict(os.environ, KUBECTL=str(work / "kubectl"),
                           MOCK_STATE=str(state), BOTH="1" if both else "0", OLD_IMAGE=IMAGE)
                result = subprocess.run(["bash", str(work / "k8s-deliver.sh"), "development",
                                         IMAGE.replace("1" * 64, "2" * 64), str(work)],
                                        env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertNotIn("ENTREGA_OK", result.stdout)
                restored = json.loads(state.read_text())
                self.assertEqual(restored["deployments"], original)
                self.assertEqual(restored["patched"], ["api", "worker"] if both else ["api"])
                self.assertIn("Versión anterior restaurada y comprobada", result.stderr)


if __name__ == "__main__":
    unittest.main()
