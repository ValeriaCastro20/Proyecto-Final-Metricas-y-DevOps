"""Fixtures for the canary's strict no-mutation backend; no network or systemd."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import met07 as core
import met07_os_watchdog_readonly as audit


class ReadOnlyCanaryTests(unittest.TestCase):
    def test_patch_scale_and_other_mutations_never_reach_subprocess(self):
        for verb in ('patch', 'scale', 'delete', 'apply', 'create', 'replace', 'edit'):
            with self.subTest(verb=verb), patch.object(core.Kubernetes, '_command') as command:
                with self.assertRaises(RuntimeError):
                    audit.ReadOnlyKubernetes.read_command(['sudo', '-n', 'k3s', 'kubectl', verb, 'deployment/event-service-worker'])
                command.assert_not_called()

    def test_read_request_reaches_reader(self):
        args = ['sudo', '-n', 'k3s', 'kubectl', '--namespace', 'eventos-development', 'get', 'deployment/event-service-worker']
        with patch.object(core.Kubernetes, '_command', return_value='{}') as command:
            self.assertEqual(audit.ReadOnlyKubernetes.read_command(args), '{}')
            command.assert_called_once_with(args)

    def test_changed_worker_cannot_be_restored_by_canary(self):
        kube = audit.ReadOnlyKubernetes('default', 'eventos-development', Path('/unused'))
        state = {'context': 'default', 'namespace': 'eventos-development', 'replicas': 1}
        with patch.object(kube, 'ready', return_value=False), patch.object(core.Kubernetes, 'scale') as scale:
            with self.assertRaises(RuntimeError):
                kube.scale(state, 1)
            scale.assert_not_called()
        with self.assertRaises(RuntimeError):
            kube.scale(state, 0)

    def test_unchanged_worker_records_noop_without_scaling(self):
        with tempfile.TemporaryDirectory() as temp:
            kube = audit.ReadOnlyKubernetes('default', 'eventos-development', temp)
            state = {'context': 'default', 'namespace': 'eventos-development', 'replicas': 1, 'uid': 'fixture'}
            with patch.object(kube, 'ready', return_value=True), patch.object(core.Kubernetes, 'scale') as scale:
                kube.scale(state, 1)
                scale.assert_not_called()
            self.assertEqual(json.loads((Path(temp) / 'readonly-noop-observed.json').read_text())['scale_mutations'], 0)
