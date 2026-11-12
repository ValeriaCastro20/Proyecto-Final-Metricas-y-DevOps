const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const v = require('./verification.cjs');
async function run(options) {
  const dir = v.newDirectory(options.output);
  const base = 'http://127.0.0.1:28000', prom = 'http://127.0.0.1:29090', graf = 'http://127.0.0.1:23000';
  const evidence = { started: new Date().toISOString(), scope: 'MET-05; eventos-development; worker remains active', records: [], passed: false };
  const get = (name, url, auth = false) => v.getJson(name, url, {
    records: evidence.records, prometheus: url.includes('/api/v1/'),
    headers: auth ? { 'X-API-Key': process.env.EVENT_ANALYST_KEY } : {},
  });
  const query = async (name, q, server = prom) => {
    const body = await get(name, server + '/api/v1/query?query=' + encodeURIComponent(q));
    v.queryResult(body);
    return body;
  };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  try {
    assert(process.env.EVENT_PRODUCER_KEY && process.env.EVENT_ANALYST_KEY, 'Both credentials required');
    const before = await get('counts-global-before', base + '/v1/reception/counts', true);
    for (const q of ['esc3_events_received_total', 'esc3_events_processed_total', 'esc3_events_backlog_total',
      'esc3_processor_duration_seconds_count']) await query('baseline-' + q, q);
    const run = 'met05-' + crypto.randomBytes(12).toString('hex');
    const binary = path.resolve('target/debug/examples/scenario_load' + (process.platform === 'win32' ? '.exe' : ''));
    const args = ['custom', '--count', '10', '--rate', '1', '--invalid', '0', '--duplicates', '0', '--late', '0', '--seed', '3', '--run', run];
    evidence.run = run;
    evidence.command = [binary, ...args];
    evidence.binary = { path: binary, sha256: crypto.createHash('sha256').update(fs.readFileSync(binary)).digest('hex'),
      sourceCommit: cp.execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim() };
    // This is the only writer of readings. Never retry this invocation automatically.
    const result = await new Promise((resolve, reject) => {
      const child = cp.spawn(binary, args, { env: { ...process.env, ESC3_BASE_URL: base }, windowsHide: true });
      let out = '';
      child.stdout.on('data', b => { out += b; });
      child.stderr.resume();
      child.on('error', reject);
      child.on('close', code => resolve({ code, out }));
    });
    const report = JSON.parse(result.out);
    evidence.generator = { exitCode: result.code, report };
    assert.equal(result.code, 0, 'Generator exit');
    assert.equal(report.passed, true);
    assert.equal(report.device_id, 'load-' + run, 'Unexpected generator device');
    assert.deepEqual(report.statuses, { '202': 10 });
    const device = report.device_id;
    let counts;
    for (let i = 0; i < 30; i++) {
      counts = await get('counts-device-poll', base + '/v1/reception/counts?device_id=' + device, true);
      if (counts.processed === 10 && counts.pending === 0) break;
      await sleep(1000);
    }
    assert.equal(counts.accepted, 10);
    assert.equal(counts.processed, 10);
    assert.equal(counts.pending, 0);
    const rows = await get('readings-final', base + '/v1/devices/' + device +
      '/readings?from=2040-01-01T00:00:00Z&to=2041-01-01T00:00:00Z&limit=100', true);
    v.readingRows(rows, device);
    await get('statistics-final', base + '/v1/devices/' + device +
      '/statistics?from=2040-01-01T00:00:00Z&to=2041-01-01T00:00:00Z', true);
    const after = await get('counts-global-after', base + '/v1/reception/counts', true);
    assert.equal(after.pending, 0);
    evidence.globalDelta = Object.fromEntries(Object.keys(after).map(k => [k, after[k] - before[k]]));
    await sleep(20000);
    v.targets(await get('targets-final', prom + '/api/v1/targets'));
    await get('rules-final', prom + '/api/v1/rules');
    const dashboard = await get('dashboard-final', graf + '/api/dashboards/uid/event-service-met05');
    const datasource = await get('datasource-final', graf + '/api/datasources/uid/event-service-prometheus');
    const expected = JSON.parse(fs.readFileSync(path.join(__dirname, '../../../dashboards/event-service-met05.json'), 'utf8'));
    v.provisioned(dashboard, expected, datasource);
    for (const panel of expected.panels) {
      for (const [suffix, server] of [['prometheus', prom],
        ['grafana', graf + '/api/datasources/proxy/uid/event-service-prometheus']]) {
        v.queryResult(await query('panel-' + panel.id + '-' + suffix, panel.targets[0].expr, server), true);
      }
    }
    for (const q of ['esc3_events_received_total', 'esc3_events_processed_total', 'esc3_events_backlog_total',
      'esc3_processor_duration_seconds_count']) await query('final-' + q, q);
    const correlation = await v.waitForCorrelation(rows, get);
    evidence.correlatedTraces = correlation.traces;
    evidence.coveredReadings = correlation.coveredReadings;
    evidence.traceQuery = correlation.query;
    evidence.passed = true;
  } catch (error) { evidence.error = error.message; throw error; }
  finally {
    evidence.finished = new Date().toISOString();
    v.writeJson(path.join(dir, '09-functional.json'), evidence);
  }
  return evidence;
}
module.exports = { run };
v.cli({ filename: __filename, run });
