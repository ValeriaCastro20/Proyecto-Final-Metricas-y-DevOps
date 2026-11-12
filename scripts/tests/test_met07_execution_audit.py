"""Offline regressions for the captured-execution audit; never contacts infrastructure."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audit_met07_execution as audit


class ExecutionAuditTests(unittest.TestCase):
    def fixture(self):
        start = {'kind': 'attempt_started', 'attempt': 0, 'device_id': 'fixture-device',
                 'event_id': 'event-0', 'request_id': 'request-0'}
        result = {**start, 'kind': 'attempt_result', 'http_status': 202, 'connection_error': None,
                  'reading_id': '00000000-0000-4000-8000-000000000001'}
        row = {'id': result['reading_id'], 'device_id': 'fixture-device', 'event_id': 'event-0',
               'received_at': '2026-11-12T21:00:01Z', 'processed_at': '2026-11-12T21:00:02Z',
               'occurred_at': '2040-01-01T00:00:00Z'}
        return [start, result], [row]

    def test_exact_pair_and_durable_association(self):
        events, rows = self.fixture()
        result, pairs = audit.reconcile(events, rows, 'fixture-device')
        self.assertTrue(result['passed'])
        self.assertEqual(result['uncertain_requests'], [])
        self.assertEqual(result['http_202'], 1)
        self.assertEqual(pairs[0]['reading_id'], rows[0]['id'])

    def test_missing_result_is_recorded_as_uncertain(self):
        events, rows = self.fixture()
        result, pairs = audit.reconcile(events[:1], rows, 'fixture-device')
        self.assertFalse(result['passed'])
        self.assertEqual(result['uncertain_requests'][0]['reason'], 'no_result')
        self.assertIsNone(result['matched_processed_uuids'])
        self.assertEqual(pairs, [])

    def test_known_status_with_connection_body_failure_is_uncertain(self):
        events, rows = self.fixture()
        events[1]['connection_error'] = 'body_timeout'
        result, _ = audit.reconcile(events, rows, 'fixture-device')
        self.assertFalse(result['passed'])
        self.assertEqual(result['uncertain_requests'][0]['reason'], 'connection_or_body_error')

    def test_missing_uuid_and_failure_status_are_never_accepted(self):
        for changes, reason in (({'reading_id': None}, 'missing_uuid'), ({'http_status': 503}, 'non_acceptance_http')):
            events, rows = self.fixture()
            events[1].update(changes)
            with self.subTest(changes=changes):
                result, _ = audit.reconcile(events, rows, 'fixture-device')
                self.assertFalse(result['passed'])
                self.assertEqual(result['uncertain_requests'][0]['reason'], reason)

    def test_orphan_or_duplicate_journal_entries_fail(self):
        events, rows = self.fixture()
        for entries in (events[1:], events + [events[0]], events + [events[1]]):
            with self.subTest(entries=entries), self.assertRaises(RuntimeError):
                audit.reconcile(entries, rows, 'fixture-device')

    def test_swapped_row_or_request_identity_fails(self):
        for target in ('row', 'result'):
            events, rows = self.fixture()
            if target == 'row':
                rows[0]['event_id'] = 'other'
            else:
                events[1]['request_id'] = 'other'
            with self.subTest(target=target), self.assertRaises(RuntimeError):
                audit.reconcile(events, rows, 'fixture-device')

    def test_absent_and_nan_metrics_are_not_converted_to_zero(self):
        def sample(result):
            return {'data': {'metrics': {'rate': {'result': result}}}}
        summary = audit.metric_summary([sample([]), sample([{'value': [0, 'NaN']}]),
                                       sample([{'value': [0, '0.5']}])], 'rate')
        self.assertEqual(summary['absent_samples'], 1)
        self.assertEqual(summary['nonfinite_values'], ['NaN'])
        self.assertEqual(summary['finite_values']['minimum'], .5)

    def test_quantiles_have_documented_nearest_rank(self):
        self.assertEqual(audit.quantiles([1, 2, 3, 4])['p95_nearest_rank'], 4)
        self.assertEqual(audit.quantiles([1, 2, 3, 4])['median'], 2.5)
        self.assertIsNone(audit.quantiles([])['median'])

    def test_snapshot_uses_its_server_sample_not_later_journal_time(self):
        event = {'kind': 'snapshot', 'mono': 10, 'data': {'server_utc': '2026-11-12T21:00:01Z'},
                 'server_anchor': {'mono': 9, 'server_utc': '2026-11-12T21:00:01Z'}}
        self.assertEqual(audit.instant(event).second, 1)
        event.pop('kind')
        self.assertEqual(audit.instant(event).second, 2)

    def test_window_rates_use_durable_times_and_ignore_fictional_occurred_at(self):
        events, rows = self.fixture()
        start = {'mono': 0, 'server_utc': '2026-11-12T21:00:00Z'}
        end = {'mono': 4, 'server_utc': '2026-11-12T21:00:04Z'}
        events[0]['mono'] = 1
        value = audit.window_counts(events, rows, start, end)
        self.assertEqual(value['attempts_per_second'], .25)
        self.assertEqual(value['received_per_second'], .25)
        self.assertEqual(value['processed_per_second'], .25)
