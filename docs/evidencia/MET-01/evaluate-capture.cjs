// Offline only. No network, application, Secrets or incident launcher.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../../..');
const source = 'docs/evidencia/MET-07/power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351/execution/incident/events.jsonl';
const raw = fs.readFileSync(path.join(root, source));
const events = raw.toString('utf8').trim().split(/\r?\n/).map(JSON.parse);
const starts = events.filter(e => e.kind === 'attempt_started');
const results = events.filter(e => e.kind === 'attempt_result');
const startIds = new Set(starts.map(e => e.attempt));
const resultIds = new Set(results.map(e => e.attempt));
assert.equal(startIds.size, starts.length, 'duplicate start');
assert.equal(resultIds.size, results.length, 'duplicate result');
assert.deepEqual(startIds, resultIds, 'unreconciled attempts');
assert.equal(results.length, 472, 'real capture population changed');
const failures = results.filter(e => e.connection_error || !Number.isInteger(e.http_status));
assert.equal(failures.length, 0, 'incomplete response population');
const N = results.length;
const businessGood = results.filter(e => [200, 202].includes(e.http_status)).length;
const good = results.filter(e => (e.http_status >= 200 && e.http_status < 300) || (e.http_status >= 400 && e.http_status < 500)).length;
const bad = N - good;
// 1 - 0.999 = 1/1000 exactly; avoid binary floating-point cancellation.
const permitted = N / 1000;
const consumption = N > 0 ? 100 * bad / permitted : null;
assert.equal(results.filter(e => e.http_status === 202).length, 472);
assert.equal(permitted, 0.472);
assert.equal(consumption, 0);
const output = {
  material: 'OFFLINE_PARTIAL_EVALUATION_OF_REAL_MET07_CAPTURE', source,
  source_sha256: crypto.createHash('sha256').update(raw).digest('hex'),
  attempts: starts.length, completed_responses: N, http_202: results.filter(e => e.http_status === 202).length, connection_errors: failures.length,
  descriptive_acceptance_percent: 100 * businessGood / N,
  slo01_v2_partial: { objective: 0.999, N, good, bad, permitted, consumption_percent: consumption },
  slo01_v2_full_24h: { status: 'N/A', reason: 'Capture does not cover 24 hours' },
  slo02_full_1h: { status: 'N/A', reason: 'Missing full-hour bucket le=0.5 and count deltas' },
};
const text = JSON.stringify(output, null, 2) + '\n';
fs.writeFileSync(path.join(__dirname, 'capture-evaluation.json'), text);
process.stdout.write(text);
