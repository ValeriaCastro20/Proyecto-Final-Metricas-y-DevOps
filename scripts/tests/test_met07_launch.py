"""Offline launcher/administrative window fixtures. Never starts the real launcher."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import met07 as core
import met07_operate as op
import met07_launch as launch


def confirmation():
    return {'source': 'user_relayed_administrator', 'external_shutdown_automations_absent': True,
            'user_accepted': True, 'arm_verified_by_agent': False, 'window_start': launch.START,
            'window_end': launch.END, 'context': 'default', 'namespace': 'eventos-development',
            'vm': 'vm-eventos-b97e31-k3s'}


class LaunchTests(unittest.TestCase):
    def test_window_boundaries_use_strict_twenty_minute_margin(self):
        for value, valid in [('2026-11-12T20:59:59Z', False), (launch.START, True),
                             ('2026-11-12T22:39:59Z', True), ('2026-11-12T22:40:00Z', False),
                             (launch.END, False), ('2026-11-13T21:00:00Z', False)]:
            with self.subTest(value=value):
                epoch = core.server_instant(value).timestamp()
                if valid:
                    self.assertGreater(launch.window(epoch)['remaining_seconds'], 1200)
                else:
                    with self.assertRaises(RuntimeError):
                        launch.window(epoch)

    def test_recovery_time_may_use_remaining_window_but_never_go_beyond_end(self):
        now = core.server_instant('2026-11-12T22:59:59Z').timestamp()
        self.assertEqual(launch.window(now, margin=False)['remaining_seconds'], 1)
        with self.assertRaises(RuntimeError):
            launch.window(core.server_instant(launch.END).timestamp(), margin=False)

    def test_administrative_clearance_requires_scope_provenance_and_valid_window(self):
        now = core.server_instant(launch.START).timestamp()
        self.assertTrue(op.administrative_window_clearance(confirmation(), now))
        for changes in ({'source': 'agent_arm_query'}, {'arm_verified_by_agent': True}, {'user_accepted': False},
                        {'external_shutdown_automations_absent': False}, {'namespace': 'eventos-production'},
                        {'context': 'other'}, {'vm': 'other'}, {'window_start': None}, {'window_end': 'bad'}):
            with self.subTest(changes=changes):
                self.assertFalse(op.administrative_window_clearance({**confirmation(), **changes}, now))
        self.assertFalse(op.administrative_window_clearance(confirmation(), now - 1))
        self.assertFalse(op.administrative_window_clearance(confirmation(), now + 6000))
        self.assertFalse(op.administrative_window_clearance(None, now))

    def power(self, scheduled_events=None, workflows=0, timers='[]'):
        now = core.server_instant(launch.START).timestamp()
        external = {'checked_server_utc': launch.START, 'next_stop_utc': '2026-11-13T05:00:00Z',
                    'azure_schedules_verified': False, 'administrator_confirmation': confirmation(),
                    'active_power_workflows': workflows}
        def reader(url, metadata):
            return {'http_status': 200, 'body': {'Events': scheduled_events or []} if 'scheduledevents' in url else
                    {'name': 'vm-eventos-b97e31-k3s'}}
        def run(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, timers if 'systemctl' in args else '', '')
        return op.power_check(external, now, reader, run)

    def test_administrative_source_does_not_claim_arm_and_does_not_bypass_local_checks(self):
        result = self.power()
        self.assertTrue(result['passed'])
        self.assertEqual(result['external_shutdown_basis'], 'user_relayed_administrator')
        self.assertIs(result['external']['azure_schedules_verified'], False)
        self.assertFalse(self.power(scheduled_events=[{'EventType': 'Reboot'}])['passed'])
        self.assertFalse(self.power(workflows=1)['passed'])
        self.assertFalse(self.power(timers='invalid')['passed'])
        self.assertFalse(self.power(timers='[{"unit": "shutdown.timer"}]')['passed'])

    def run_row(self, run_id, status='completed', workflow_id=launch.POWER_WORKFLOW_ID):
        return {'id': run_id, 'workflow_id': workflow_id, 'status': status,
                'name': 'Power workflow' if workflow_id == launch.POWER_WORKFLOW_ID else 'Rust quality and acceptance'}

    def response(self, rows, total=None):
        return {'http_status': 200, 'body': {'total_count': len(rows) if total is None else total,
                                           'workflow_runs': rows}}

    def test_five_queued_rust_ci_runs_do_not_block_power_admission(self):
        rust = [self.run_row(i, 'queued', 123) for i in range(1, 6)]
        power = [self.run_row(6)]
        calls = []
        def reader(url):
            calls.append(url)
            if url.startswith(launch.POWER_RUNS + '?'):
                return self.response(power)
            # The old repository-wide query would return the five queued CI jobs.
            if '/actions/runs?' in url:
                return self.response(rust + power)
            raise AssertionError('Unapproved workflow query')
        result = launch.workflow_review(reader)
        self.assertEqual(result['active'], [])
        self.assertTrue(self.power(workflows=len(result['active']))['passed'])
        self.assertEqual(calls, [launch.POWER_RUNS + '?per_page=100&page=1'])
        self.assertTrue(result['inventory_complete'])

    def test_pending_or_active_power_workflow_blocks_admission(self):
        for status in ('queued', 'pending', 'in_progress', 'waiting', 'requested'):
            with self.subTest(status=status):
                result = launch.workflow_review(lambda url: self.response([self.run_row(1, status)]))
                self.assertEqual(len(result['active']), 1)
                self.assertFalse(self.power(workflows=len(result['active']))['passed'])

    def test_power_workflow_pagination_includes_active_run_on_second_page(self):
        calls = []
        def reader(url):
            calls.append(url)
            rows = [self.run_row(i) for i in range(1, 101)] if '&page=1' in url else [self.run_row(101, 'pending')]
            return self.response(rows, 101)
        result = launch.workflow_review(reader)
        self.assertEqual(result['total_count'], 101)
        self.assertEqual([row['page'] for row in result['pages']], [1, 2])
        self.assertEqual(result['active'][0]['id'], 101)
        self.assertFalse(self.power(workflows=len(result['active']))['passed'])
        self.assertEqual(calls, [launch.POWER_RUNS + '?per_page=100&page=1',
                                 launch.POWER_RUNS + '?per_page=100&page=2'])

    def test_http_or_connection_errors_never_return_approval(self):
        for response in ({'http_status': 403}, {'http_status': 500},
                         {'http_status': None, 'connection_error': 'timeout'},
                         {'http_status': 200, 'connection_error': 'invalid_response'}):
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                launch.workflow_review(lambda url: response)
        def second_page_error(url):
            return self.response([self.run_row(i) for i in range(1, 101)], 101) if '&page=1' in url else {'http_status': 503}
        with self.assertRaisesRegex(RuntimeError, 'query failed'):
            launch.workflow_review(second_page_error)

    def test_incomplete_changed_or_duplicate_pagination_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'pagination incomplete'):
            launch.workflow_review(lambda url: self.response([self.run_row(1)], 2))
        for tail in (self.response([], 101), self.response([self.run_row(101)], 102),
                     self.response([self.run_row(1)], 101)):
            with self.subTest(tail=tail), self.assertRaises(RuntimeError):
                launch.workflow_review(lambda url: self.response([self.run_row(i) for i in range(1, 101)], 101)
                                       if '&page=1' in url else tail)
        with patch.object(launch, 'MAX_WORKFLOW_PAGES', 1), self.assertRaisesRegex(RuntimeError, 'page limit'):
            launch.workflow_review(lambda url: self.response([self.run_row(i) for i in range(1, 101)], 101))

    def test_invalid_or_foreign_inventory_fails_closed_and_empty_is_valid(self):
        self.assertEqual(launch.workflow_review(lambda url: self.response([]))['active'], [])
        invalid = [{'http_status': 200, 'body': {}},
                   {'http_status': 200, 'body': {'total_count': True, 'workflow_runs': []}},
                   self.response([self.run_row(1, workflow_id=123)]),
                   self.response([{'id': 1, 'workflow_id': launch.POWER_WORKFLOW_ID}])]
        for response in invalid:
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                launch.workflow_review(lambda url: response)

    def test_precondition_failure_closes_forwards_and_never_enters_incident(self):
        with tempfile.TemporaryDirectory() as temp:
            payload = {'administrator_confirmation': confirmation(), 'authorization': {'incident_authorized': True, 'isolated': True, 'isolation_review_ref': 'fixture',
                       'context': 'default', 'namespace': 'eventos-development', 'deployment_uid': launch.UID},
                       'execute_once': True, 'source_sha256': {},
                       'EVENT_PRODUCER_KEY': 'fixture-only-producer', 'EVENT_ANALYST_KEY': 'fixture-only-analyst'}
            forwards = Mock(children=[])
            kube = Mock()
            kube.get.return_value = {'metadata': {'uid': launch.UID}, 'spec': {'replicas': 1},
                                     'status': {'readyReplicas': 1, 'availableReplicas': 1}}
            with patch.object(launch, 'Forwards', return_value=forwards), patch.object(core, 'Kubernetes', return_value=kube), \
                 patch.object(launch.time, 'time', return_value=core.server_instant(launch.START).timestamp()), \
                 patch.dict(launch.os.environ), patch.object(op, 'guard_probe') as probe, patch.object(core, 'Experiment') as experiment:
                runner = launch.Launch(payload, Path(temp))
                runner.preflight = Mock(side_effect=RuntimeError('fixture blocked'))
                with self.assertRaisesRegex(RuntimeError, 'fixture blocked'):
                    runner.run()
                probe.assert_not_called()
                experiment.assert_not_called()
                kube.scale.assert_not_called()
                forwards.close.assert_called_once()
                self.assertFalse((Path(temp) / 'incident-entry-claimed.json').exists())

    def test_absent_one_shot_authorization_never_opens_forwards(self):
        with tempfile.TemporaryDirectory() as temp:
            payload = {"administrator_confirmation": confirmation(), "authorization": {}}
            forwards = Mock(children=[])
            with patch.object(launch, "Forwards", return_value=forwards), patch.object(core, "Kubernetes"):
                runner = launch.Launch(payload, Path(temp))
                with self.assertRaisesRegex(RuntimeError, "one-shot authorization"):
                    runner.run()
                forwards.start.assert_not_called()

    def test_dead_forward_blocks_transport(self):
        forwards = launch.Forwards(Path("/unused"), Mock())
        children = [Mock() for _ in range(4)]
        for child in children:
            child.poll.return_value = None
        forwards.children = [("fixture", 1, child, Mock()) for child in children]
        forwards.verify()
        children[2].poll.return_value = 1
        with self.assertRaisesRegex(RuntimeError, "four VM forwards"):
            forwards.verify()

    def test_device_write_cannot_reach_http_before_window(self):
        client = launch.LiveHttp(Mock())
        with patch.object(launch.time, "time", return_value=core.server_instant(launch.START).timestamp() - 1), \
             patch.object(core.Http, "request") as request:
            with self.assertRaisesRegex(RuntimeError, "outside authorized window"):
                client.request(client.api, "POST", "/v1/devices", {}, "producer")
            request.assert_not_called()
