"""Offline audit of one captured MET-07 execution. No network, Kubernetes or load."""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import statistics

import met07 as core


def quantiles(values):
    values = sorted(values)
    if not values:
        return {'count': 0, 'minimum': None, 'median': None, 'p95_nearest_rank': None, 'maximum': None}
    return {'count': len(values), 'minimum': values[0], 'median': statistics.median(values),
            'p95_nearest_rank': values[math.ceil(.95 * len(values)) - 1], 'maximum': values[-1]}


def reconcile(events, rows, device):
    associations, unresolved = core.attempt_associations(events, device, strict=False)
    starts = {e['attempt']: e for e in events if e.get('kind') == 'attempt_started'}
    results = {e['attempt']: e for e in events if e.get('kind') == 'attempt_result'}
    uncertain = []
    for number in unresolved:
        result = results.get(number)
        uncertain.append({'attempt': number, 'event_id': starts[number]['event_id'],
                          'reason': 'no_result' if result is None else
                          'connection_or_body_error' if result.get('connection_error') else
                          'non_acceptance_http' if result.get('http_status') not in (200, 202) else 'missing_uuid'})
    if uncertain:
        return {'passed': False, 'uncertain_requests': uncertain, 'started': len(starts),
                'results': len(results), 'matched_processed_uuids': None}, []
    ids = core.processed(events, rows, device)
    pairs = [{'attempt': number, 'event_id': start['event_id'], 'request_id': start.get('request_id'),
              'reading_id': results[number]['reading_id'], 'http_status': results[number]['http_status']}
             for number, start in sorted(starts.items())]
    return {'passed': True, 'uncertain_requests': [], 'started': len(starts), 'results': len(results),
            'http_202': sum(e['http_status'] == 202 for e in results.values()),
            'http_200': sum(e['http_status'] == 200 for e in results.values()),
            'unique_response_uuids': len(associations), 'matched_processed_uuids': len(ids),
            'duplicate_response_uuids': len(results) - len(associations),
            'connection_errors': sum(bool(e.get('connection_error')) for e in results.values())}, pairs


def instant(event):
    if event.get('kind') == 'snapshot':
        return core.server_instant(event['data']['server_utc'])
    if event.get('server_utc'):
        return core.server_instant(event['server_utc'])
    anchor = event['server_anchor']
    return core.server_instant(anchor['server_utc']) + dt.timedelta(seconds=event['mono'] - anchor['mono'])


def window_counts(events, rows, start, end):
    lower, upper = instant(start), instant(end)
    seconds = (upper - lower).total_seconds()
    core.require(seconds > 0, 'Empty measurement window')
    attempts = sum(e.get('kind') == 'attempt_started' and start['mono'] <= e['mono'] < end['mono'] for e in events)
    received = sum(lower <= core.server_instant(r['received_at']) < upper for r in rows)
    processed = sum(lower <= core.server_instant(r['processed_at']) < upper for r in rows)
    return {'start_utc': lower.isoformat(), 'end_utc': upper.isoformat(), 'seconds': seconds, 'monotonic_seconds': end['mono'] - start['mono'],
            'attempts': attempts, 'durably_received': received, 'durably_processed': processed,
            'attempts_per_second': attempts / seconds, 'received_per_second': received / seconds,
            'processed_per_second': processed / seconds,
            'boundary_method': 'server UTC fields or Prometheus anchor plus monotonic event offset; half-open interval'}


def metric_summary(samples, name):
    values, absent, nonfinite = [], 0, []
    for sample in samples:
        result = sample['data']['metrics'][name]['result']
        if not result:
            absent += 1
        for row in result:
            raw = row['value'][1]
            value = float(raw)
            if math.isfinite(value):
                values.append(value)
            else:
                nonfinite.append(raw)
    return {'samples': len(samples), 'absent_samples': absent, 'nonfinite_values': nonfinite,
            'finite_values': quantiles(values)}


def audit(source):
    source = Path(source)
    read = lambda name: json.loads((source / name).read_text(encoding='utf-8-sig'))
    events = [json.loads(line) for line in (source / 'incident/events.jsonl').read_text().splitlines()]
    rows, acceptance = read('incident/after-readings.json'), read('incident/acceptance.json')
    reconciliation, pairs = reconcile(events, rows, acceptance['device_id'])
    core.require(reconciliation['passed'], 'Uncertain requests; see reconciliation before claiming acceptance')
    core.require(reconciliation['http_202'] == 472 and reconciliation['started'] == 472 and
                 reconciliation['matched_processed_uuids'] == 472 and reconciliation['duplicate_response_uuids'] == 0,
                 'Unexpected incident cardinality')
    snapshots = [e for e in events if e['kind'] == 'snapshot']
    event = lambda kind: next(e for e in events if e['kind'] == kind)
    zero, restore, ready = (event(kind) for kind in ('zero_worker_pods', 'restore_requested', 'worker_ready'))
    first_after = next(e for e in snapshots if e['phase'] == 'after')
    first_zero = next(e for e in snapshots if e['phase'] == 'after' and e['data']['backlog'] == 0)
    resolved = next(e for e in snapshots if e['phase'] == 'after' and e['data']['alert_state'] == 'inactive' and e['data']['backlog'] == 0)
    firing = event('firing_observed')
    core.require(firing['mono'] < restore['mono'] < ready['mono'] < first_zero['mono'] < resolved['mono'], 'Chronology mismatch')
    core.require(all(e['data']['rule'] == {'query': 'esc3_events_backlog_total > 100', 'duration': 120} for e in snapshots), 'Rule changed')
    core.require([instant(e).strftime('%H:%M:%S') for e in (firing, ready, first_zero, resolved)] ==
                 ['21:35:03', '21:35:07', '21:35:09', '21:36:01'], 'Expected UTC chronology differs')
    core.require(set(acceptance['processed_ids']) == {r['id'] for r in rows}, 'Acceptance UUID mismatch')
    control, worker = read('incident/control-result.json'), read('final-worker.json')
    core.require(control['normal_firing_path'] and control['restore_requested'] and control['failure'] is None, 'Failed control')
    core.require(worker['replicas'] == worker['ready'] == worker['available'] == 1, 'Final worker mismatch')
    boundaries = {e['phase']: core.server_instant(e['server_utc']) for e in events
                  if e.get('kind') == 'signal_phase_boundary'}
    reception_groups = {'before': [], 'during': [], 'after': []}
    for row in rows:
        received = core.server_instant(row['received_at'])
        phase = 'before' if received < boundaries['during'] else 'during' if received < boundaries['after'] else 'after'
        reception_groups[phase].append((core.server_instant(row['processed_at']) - received).total_seconds())
    delays = [(core.server_instant(r['processed_at']) - core.server_instant(r['received_at'])).total_seconds() for r in rows]
    results = {e['attempt']: e for e in events if e['kind'] == 'attempt_result'}
    client_elapsed = [results[e['attempt']]['mono'] - e['mono'] for e in events if e['kind'] == 'attempt_started']
    baseline_samples = [e for e in snapshots if e['phase'] == 'before' and e['data']['counts']['accepted'] < 472]
    baseline = {'start_utc': baseline_samples[0]['data']['server_utc'], 'end_utc': baseline_samples[-1]['data']['server_utc']}
    elapsed = (core.server_instant(baseline['end_utc']) - core.server_instant(baseline['start_utc'])).total_seconds()
    baseline.update(seconds=elapsed, received_delta=baseline_samples[-1]['data']['counts']['received']-baseline_samples[0]['data']['counts']['received'],
                    processed_delta=baseline_samples[-1]['data']['counts']['processed']-baseline_samples[0]['data']['counts']['processed'])
    baseline.update(received_per_second=baseline['received_delta']/elapsed, processed_per_second=baseline['processed_delta']/elapsed,
                    method='device-scoped durable counter delta between the two active-baseline snapshots; short comparison, not steady-state capacity')
    metrics = {phase: {name: metric_summary([e for e in snapshots if e['phase'] == phase], name)
                      for name in ('input_per_second', 'processed_per_second', 'http_p95_seconds', 'http_5xx_per_second')}
               for phase in ('before', 'during', 'after')}
    return {'material': 'OFFLINE_AUDIT_OF_REAL_CAPTURED_EXECUTION', 'passed': True,
            'reconciliation': reconciliation, 'timeline': {name: {'utc': instant(value).isoformat(), 'mono': value['mono']}
            for name, value in [('firing', firing), ('restore_requested', restore), ('worker_ready', ready),
                                ('first_zero_backlog', first_zero), ('inactive', resolved)]},
            'baseline_counter_comparison': baseline, 'zero_worker_until_restore': window_counts(events, rows, zero, restore),
            'restore_until_first_durable_after_snapshot': window_counts(events, rows, restore, first_after),
            'zero_worker_until_ready': window_counts(events, rows, zero, ready),
            'durable_received_to_processed_seconds': quantiles(delays),
            'durable_delay_grouped_by_reception_phase': {phase: quantiles(values) for phase, values in reception_groups.items()},
            'client_journal_start_to_result_seconds': quantiles(client_elapsed),
            'client_latency_scope': 'includes pre-send journal fsync and body decoding; not pure HTTP server latency',
            'prometheus_rolling_one_minute_metrics': metrics,
            'durations_seconds': {'zero_pods_to_firing': firing['mono']-zero['mono'],
                                  'degradation_to_firing': firing['mono']-event('degradation_started')['mono'],
                                  'restore_request_to_ready': ready['mono']-restore['mono'],
                                  'restore_request_to_backlog_zero': first_zero['mono']-restore['mono'],
                                  'restore_request_to_inactive': resolved['mono']-restore['mono']},
            'maximum_observed_backlog': max(e['data']['backlog'] for e in snapshots),
            'source_sha256': [{'sha256': hashlib.sha256((source/name).read_bytes()).hexdigest(), 'path': name}
                              for name in ('incident/events.jsonl', 'incident/after-readings.json', 'incident/acceptance.json')]}, pairs


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result, mappings = audit(args.source)
    with args.output.open('x', encoding='utf-8', newline='\n') as target:
        json.dump({'audit': result, 'uuid_mapping': mappings}, target, ensure_ascii=False, indent=2, allow_nan=False)
        target.write('\n')
    print(json.dumps(result, allow_nan=False))
