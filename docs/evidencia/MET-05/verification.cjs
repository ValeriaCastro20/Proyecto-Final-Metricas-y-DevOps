const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const cp = require('node:child_process');
const crypto = require('node:crypto');

const jobs = ['event-service', 'event-service-worker'];
function options(args = process.argv.slice(2)) {
  const result = {};
  assert.equal(args.length % 2, 0, 'Expected --option value pairs');
  for (let i = 0; i < args.length; i += 2) {
    assert(['--output', '--functional', '--correlation'].includes(args[i]), 'Unknown option');
    assert(!result[args[i].slice(2)], 'Repeated option');
    result[args[i].slice(2)] = args[i + 1];
  }
  return result;
}
function newDirectory(output) {
  assert(output, 'Explicit --output NEW_DIRECTORY required; original evidence is read-only');
  const dir = path.resolve(output);
  fs.mkdirSync(dir); // Exclusive: never reuse a directory or overwrite historical evidence.
  return dir;
}
function writeJson(file, value) {
  const data = JSON.stringify(value, null, 2) + '\n';
  for (const secret of [process.env.EVENT_PRODUCER_KEY, process.env.EVENT_ANALYST_KEY].filter(Boolean)) {
    assert(!data.includes(secret), 'Credential detected; evidence not written');
  }
  fs.writeFileSync(file, data, { flag: 'wx' });
}
async function getJson(name, url, { records = [], prometheus = false, headers = {}, fetcher = fetch } = {}) {
  const response = await fetcher(url, { redirect: 'error', headers, signal: AbortSignal.timeout(15000) });
  const record = { name, url, http: response.status, utc: new Date().toISOString() };
  records.push(record);
  record.body = await response.json();
  assert.equal(response.status, 200, name + ' HTTP');
  if (prometheus) assert.equal(record.body.status, 'success', name + ' Prometheus status');
  return record.body;
}
function targets(body) {
  assert.equal(body.status, 'success');
  assert(Array.isArray(body.data?.activeTargets), 'Missing activeTargets');
  for (const job of jobs) {
    const found = body.data.activeTargets.filter(t => t.labels?.job === job);
    assert(found.length > 0, 'Missing target: ' + job);
    assert(found.every(t => t.health === 'up' && !t.lastError), 'Unhealthy target: ' + job);
  }
}
function provisioned(live, expected, datasource) {
  assert.equal(datasource.uid, 'event-service-prometheus', 'Datasource UID');
  assert.equal(datasource.type, 'prometheus', 'Datasource type');
  assert.equal(datasource.readOnly, true, 'Datasource must be provisioned read-only');
  assert.equal(live.meta?.provisioned, true, 'Dashboard must be provisioned');
  assert.equal(live.dashboard?.uid, expected.uid, 'Dashboard UID');
  assert.equal(live.dashboard?.panels?.length, 8, 'Expected eight panels');
  assert.equal(expected.panels.length, 8);
  assert.equal(new Set(live.dashboard.panels.map(p => p.id)).size, 8, 'Duplicate panels');
  for (const panel of expected.panels) {
    const actual = live.dashboard.panels.find(p => p.id === panel.id);
    assert(actual, 'Missing panel ' + panel.id);
    assert.equal(actual.datasource?.uid, 'event-service-prometheus', 'Panel datasource');
    assert.deepEqual(actual.targets, panel.targets, 'Panel queries differ');
  }
}
function queryResult(body, requireData = false) {
  assert.equal(body.status, 'success', 'Prometheus status');
  assert.equal(body.data?.resultType, 'vector', 'Expected instant vector');
  assert(Array.isArray(body.data.result), 'Missing query result');
  if (requireData) {
    assert(body.data.result.length > 0, 'Missing panel series');
    assert(body.data.result.some(s => Array.isArray(s.value) && s.value[1] !== '' &&
      Number.isFinite(Number(s.value[1]))), 'No finite panel observation');
  }
}
function readingRows(rows, device) {
  assert(Array.isArray(rows) && rows.length === 10, 'Expected ten readings');
  assert(rows.every(r => typeof r.id === 'string' && r.id.length > 0), 'Missing reading UUID');
  assert.equal(new Set(rows.map(r => r.id)).size, 10, 'Expected ten unique readings');
  if (device) assert(rows.every(r => r.device_id === device), 'Readings from another device');
  for (const r of rows) {
    assert(Number.isFinite(Date.parse(r.received_at)), 'Invalid server received_at');
    assert(Number.isFinite(Date.parse(r.processed_at)), 'Invalid server processed_at');
    assert(Date.parse(r.processed_at) >= Date.parse(r.received_at), 'Processing precedes reception');
  }
  return rows;
}
function serverWindow(rows) {
  readingRows(rows);
  return {
    start: (Math.min(...rows.map(r => Date.parse(r.received_at))) - 60000) * 1000,
    end: (Math.max(...rows.map(r => Date.parse(r.processed_at))) + 60000) * 1000,
  };
}
function safeTraces(traces) {
  assert(Array.isArray(traces), 'Missing Jaeger traces');
  return traces.map(t => ({
    traceID: t.traceID,
    processes: Object.fromEntries(Object.entries(t.processes).map(([k, p]) => [k, { serviceName: p.serviceName }])),
    spans: t.spans.map(s => ({
      spanID: s.spanID, operationName: s.operationName, processID: s.processID,
      startTime: s.startTime, duration: s.duration, references: s.references,
      tags: s.tags.filter(k => ['component', 'route', 'status', 'reading_id', 'otel.kind'].includes(k.key)),
    })),
  }));
}
function correlate(rows, traces) {
  readingRows(rows);
  const ids = new Set(rows.map(r => r.id)), covered = new Set(), matched = [];
  for (const t of traces) {
    let relevant = false;
    for (const w of t.spans) {
      const id = w.tags.find(k => k.key === 'reading_id')?.value;
      if (w.operationName !== 'process_reading' || !ids.has(id)) continue;
      relevant = true;
      assert.equal(t.processes[w.processID]?.serviceName, 'event-service-worker', 'Worker service');
      const parent = w.references.find(r => r.refType === 'CHILD_OF' && r.traceID === t.traceID);
      assert(parent, 'Missing same-trace CHILD_OF');
      const a = t.spans.find(s => s.spanID === parent.spanID);
      assert.equal(a?.operationName, 'http_request', 'Missing API parent');
      assert.equal(t.processes[a.processID]?.serviceName, 'event-service-api', 'API service');
      assert(a.tags.some(k => k.key === 'route' && k.value === '/v1/readings'), 'API route');
      assert(a.tags.some(k => k.key === 'status' && String(k.value) === '202'), 'API status');
      covered.add(id);
    }
    if (relevant) matched.push(t);
  }
  assert.equal(covered.size, 10, 'Expected correlation of all ten readings');
  return { traces: matched, coveredReadings: [...covered] };
}
async function waitForCorrelation(rows, get, { attempts = 12, sleep = ms => new Promise(r => setTimeout(r, ms)) } = {}) {
  const window = serverWindow(rows);
  const url = 'http://127.0.0.1:26686/api/traces?service=event-service-worker&operation=process_reading&limit=100&start=' +
    window.start + '&end=' + window.end;
  for (let i = 0; i < attempts; i++) {
    const body = await get('jaeger-reading-traces', url); // HTTP failures must propagate.
    assert(!body.errors?.length, 'Jaeger query errors');
    const traces = safeTraces(body.data);
    try { return { ...correlate(rows, traces), query: window, url }; }
    catch (error) {
      if (i === attempts - 1) throw error;
      await sleep(5000);
    }
  }
  throw Error('No correlation attempts');
}
function sameRun(source, correlation, sourceBytes) {
  const report = source.generator?.report;
  assert(typeof report?.run === 'string' && report.run.length > 0, 'Missing run identifier');
  assert.equal(source.run, report.run, 'Different functional run');
  assert.equal(report.device_id, 'load-' + report.run, 'Device/run mismatch');
  assert.equal(source.generator?.exitCode, 0, 'Generator exit');
  assert.equal(report?.passed, true, 'Generator failed');
  assert(source.passed === true || (source.passed === false &&
    source.error === 'API to worker parent correlation'), 'Unrelated functional failure');
  const rows = readingRows(source.records.find(r => r.name === 'readings-final')?.body, report.device_id);
  assert.equal(correlation.passed, true, 'Correlation failed');
  assert.equal(correlation.device_id, report.device_id, 'Different execution/device');
  assert.equal(correlation.coveredReadings?.length, 10);
  assert.deepEqual([...correlation.coveredReadings].sort(), rows.map(r => r.id).sort(), 'Different covered readings');
  const linked = correlate(rows, correlation.traces); // Do not trust flags alone.
  assert.equal(linked.traces.length, correlation.traces.length, 'Unrelated traces in correlation evidence');
  if (correlation.sourceSha256) {
    assert(sourceBytes, 'Source bytes required for digest');
    assert.equal(correlation.sourceSha256, crypto.createHash('sha256').update(sourceBytes).digest('hex'), 'Source digest mismatch');
  }
  return { rows, trace: correlation.traces[0].traceID };
}
function capture(name, url, output, { spawn = cp.spawnSync, browser = 'C:/Program Files/Google/Chrome/Application/chrome.exe' } = {}) {
  assert.equal(path.basename(name), name, 'Invalid screenshot name');
  assert(!fs.existsSync(path.join(output, name)), 'Existing screenshot rejected');
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'met05-capture-'));
  const file = path.join(temp, name), started = Date.now();
  const args = ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--user-data-dir=' + path.join(temp, 'profile'), '--window-size=1800,1800',
    '--virtual-time-budget=15000', '--screenshot=' + file, url];
  const r = spawn(browser, args, { encoding: 'utf8', timeout: 55000, windowsHide: true });
  const entry = { name, url, utc: new Date().toISOString(), exit: r.status, error: r.error?.code, fresh: false };
  try {
    assert(!r.error && r.status === 0, 'Browser failed');
    assert(fs.existsSync(file), 'Browser did not create a new screenshot');
    assert(fs.statSync(file).mtimeMs >= started - 1000, 'Stale screenshot');
    assert(fs.readFileSync(file).subarray(0, 8).equals(Buffer.from('89504e470d0a1a0a', 'hex')), 'Invalid PNG');
    fs.copyFileSync(file, path.join(output, name), fs.constants.COPYFILE_EXCL);
    entry.fresh = true;
  } catch (error) { entry.failure = error.message; }
  return entry;
}
function captures(shots, output, dependencies) {
  const records = shots.map(([name, url]) => capture(name, url, output, dependencies));
  writeJson(path.join(output, 'screenshots.json'), { records, passed: records.every(r => r.fresh) });
  assert(records.every(r => r.fresh), 'Screenshot capture failed; inspect screenshots.json');
}
function cli(main) {
  if (require.main?.filename === main.filename) main.run(options()).catch(error => {
    console.error(error.message); process.exitCode = 1;
  });
}
module.exports = { options, newDirectory, writeJson, getJson, targets, provisioned, queryResult,
  readingRows, serverWindow, safeTraces, correlate, waitForCorrelation, sameRun, capture, captures, cli };
