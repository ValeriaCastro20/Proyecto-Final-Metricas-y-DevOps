const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const cp = require('node:child_process');
const crypto = require('node:crypto');
const v = require('../verification.cjs');
const verify = require('../05-verify.cjs');
const root = path.resolve(__dirname, '..');
const sourceBytes = fs.readFileSync(path.join(root, '09-functional.json'));
const source = JSON.parse(sourceBytes);
const correlation = JSON.parse(fs.readFileSync(path.join(root, '10-correlation.json'), 'utf8'));
const rows = source.records.find(r => r.name === 'readings-final').body;
const clone = x => JSON.parse(JSON.stringify(x));
const temporary = () => fs.mkdtempSync(path.join(os.tmpdir(), 'met05-negative-'));
const destination = () => path.join(temporary(), 'new-run');
const body = (b, status = 200) => ({ status, json: async () => clone(b) });
const fixtures = JSON.parse(fs.readFileSync(path.join(root, '05-verification.json'), 'utf8')).records;
const fakeFetch = change => async url => {
  const record = fixtures.find(r => r.url === url);
  assert(record, 'Unexpected URL (network disabled): ' + url);
  const response = { status: record.http, data: clone(record.body) };
  change?.(url, response);
  return body(response.data, response.status);
};

test('HTTP and Prometheus errors fail after recording the response', async () => {
  for (const [status, data] of [[404, { message: 'missing' }], [200, { status: 'error', error: 'bad query' }]]) {
    const records = [];
    await assert.rejects(v.getJson('fixture', 'http://fixture.invalid', {
      records, prometheus: true, fetcher: async () => body(data, status),
    }));
    assert.equal(records[0].http, status);
    assert.deepEqual(records[0].body, data);
  }
});
test('non-JSON HTTP errors preserve status; invalid successful JSON still fails', async () => {
  for (const status of [404, 500, 200]) {
    const records = [];
    await assert.rejects(v.getJson('fixture', 'http://fixture.invalid', {
      records, fetcher: async () => ({ status, json: async () => { throw SyntaxError('HTML response'); } }),
    }), status === 200 ? /HTML response/ : error => error.actual === status && /fixture HTTP/.test(error.message));
    assert.equal(records[0].http, status);
    if (status !== 200) assert.equal(records[0].bodyError, 'HTML response');
  }
});
test('05 accepts the captured provisioned configuration with isolated responses', async () => {
  const output = destination();
  assert.equal((await verify.run({ output }, { fetcher: fakeFetch() })).passed, true);
});
for (const [name, mutate] of [
  ['dashboard HTTP 404', (url, r) => { if (url.includes('/api/dashboards/')) r.status = 404; }],
  ['Prometheus HTTP-200 error', (url, r) => { if (url.includes('/api/v1/query')) r.data = { status: 'error' }; }],
  ['unprovisioned dashboard', (url, r) => { if (url.includes('/api/dashboards/')) r.data.meta.provisioned = false; }],
  ['missing panel', (url, r) => { if (url.includes('/api/dashboards/')) r.data.dashboard.panels.pop(); }],
  ['wrong datasource', (url, r) => { if (url.includes('/api/datasources/uid/')) r.data.uid = 'wrong'; }],
  ['mutable datasource', (url, r) => { if (url.includes('/api/datasources/uid/')) r.data.readOnly = false; }],
  ['wrong provisioned query', (url, r) => {
    if (url.includes('/api/dashboards/')) r.data.dashboard.panels[0].targets[0].expr = 'up';
  }],
  ['wrong panel type', (url, r) => { if (url.includes('/api/dashboards/')) r.data.dashboard.panels[0].type = 'stat'; }],
  ['wrong panel title', (url, r) => { if (url.includes('/api/dashboards/')) r.data.dashboard.panels[0].title = 'Other'; }],
  ['wrong panel unit', (url, r) => { if (url.includes('/api/dashboards/')) r.data.dashboard.panels[0].fieldConfig.defaults.unit = 'bytes'; }],
]) test('05 rejects ' + name + ' and preserves failure details in a NEW directory', async () => {
  const output = destination();
  await assert.rejects(verify.run({ output }, { fetcher: fakeFetch(mutate) }));
  const evidence = JSON.parse(fs.readFileSync(path.join(output, '05-verification.json'), 'utf8'));
  assert.equal(evidence.passed, false);
  assert(evidence.error);
  assert(evidence.records.length > 0);
});
const healthy = () => ({ status: 'success', data: { activeTargets: vTargets() } });
function vTargets() { return ['event-service', 'event-service-worker'].map(job => ({ labels: { job }, health: 'up', lastError: '' })); }
test('both jobs and every matching target must be healthy', () => {
  v.targets(healthy());
  for (const targets of [[], vTargets().slice(0, 1), vTargets().slice(1),
    vTargets().map(t => ({ ...t, health: 'down' })),
    [...vTargets(), { labels: { job: 'event-service-worker' }, health: 'down' }],
    vTargets().map(t => ({ ...t, lastError: 'scrape failed' }))]) {
    assert.throws(() => v.targets({ status: 'success', data: { activeTargets: targets } }));
  }
});
test('Jaeger window uses durable timestamps despite local clock skew', async () => {
  const expected = v.serverWindow(rows);
  const originalNow = Date.now;
  Date.now = () => Date.parse('2099-01-01T00:00:00Z');
  try {
    await v.waitForCorrelation(rows, async (name, url) => {
      const q = new URL(url).searchParams;
      assert.equal(Number(q.get('start')), expected.start);
      assert.equal(Number(q.get('end')), expected.end);
      return { data: correlation.traces };
    });
  } finally { Date.now = originalNow; }
  for (const field of ['received_at', 'processed_at']) {
    const invalid = clone(rows); invalid[0][field] = null;
    assert.throws(() => v.serverWindow(invalid));
  }
});
test('partial correlation never succeeds; polling waits for all ten', async () => {
  for (const count of [0, 1, 9]) {
    assert.throws(() => v.correlate(rows, correlation.traces.slice(0, count)));
    await assert.rejects(v.waitForCorrelation(rows, async () => ({ data: correlation.traces.slice(0, count) }),
      { attempts: 2, sleep: async () => {} }));
  }
  let calls = 0;
  const result = await v.waitForCorrelation(rows, async () => ({
    data: ++calls === 1 ? correlation.traces.slice(0, 9) : correlation.traces,
  }), { attempts: 2, sleep: async () => {} });
  assert.equal(calls, 2);
  assert.equal(result.coveredReadings.length, 10);
});
test('correlation rejects broken parent, service, route, status and duplicate UUIDs', () => {
  for (const mutate of [
    w => { w.references = []; },
    w => { w.references[0].traceID = 'different-trace'; },
    (w, t) => { t.processes[w.processID].serviceName = 'wrong-service'; },
    (w, t) => { t.spans.find(s => s.operationName === 'http_request').tags.find(k => k.key === 'route').value = '/health/ready'; },
    (w, t) => { t.spans.find(s => s.operationName === 'http_request').tags.find(k => k.key === 'status').value = '500'; },
  ]) {
    const traces = clone(correlation.traces), t = traces[0];
    mutate(t.spans.find(s => s.operationName === 'process_reading'), t);
    assert.throws(() => v.correlate(rows, traces));
  }
  const duplicate = clone(rows); duplicate[0] = duplicate[1];
  assert.throws(() => v.correlate(duplicate, correlation.traces));
});
test('Jaeger HTTP failures propagate without treating an empty result as success', async () => {
  await assert.rejects(v.waitForCorrelation(rows, () => v.getJson('Jaeger', 'http://fixture.invalid', {
    fetcher: async () => body({ data: [] }, 500),
  }), { attempts: 1 }));
});
test('same-run validation accepts preserved historical failure only with complete correction', () => {
  v.sameRun(source, correlation, sourceBytes);
  for (const mutate of [
    c => { c.device_id = 'load-another-run'; },
    c => { c.coveredReadings[0] = 'another-reading'; },
    c => { c.coveredReadings[0] = c.coveredReadings[1]; },
    c => { c.traces = c.traces.slice(0, 9); },
    c => { c.sourceSha256 = 'wrong-digest'; },
  ]) {
    const altered = clone(correlation); mutate(altered);
    assert.throws(() => v.sameRun(source, altered, sourceBytes));
  }
  const failed = clone(source); failed.error = 'metrics failed';
  assert.throws(() => v.sameRun(failed, correlation, sourceBytes));
  const bound = { ...correlation, sourceSha256: crypto.createHash('sha256').update(sourceBytes).digest('hex') };
  v.sameRun(source, bound, sourceBytes);
});
test('screenshots reject mixed runs before opening any browser', async () => {
  const dir = temporary(), file = path.join(dir, 'correlation.json');
  fs.writeFileSync(file, JSON.stringify({ ...correlation, device_id: 'other' }));
  await assert.rejects(require('../09-screenshots.cjs').run({
    functional: path.join(root, '09-functional.json'), correlation: file, output: path.join(dir, 'shots'),
  }, { spawn: () => { throw Error('Browser must not start'); } }), /Different execution/);
});
test('new outputs cannot reuse directories or overwrite original evidence', () => {
  assert.throws(() => v.newDirectory(root));
  assert.throws(() => v.newDirectory());
  const file = path.join(temporary(), 'existing.json');
  fs.writeFileSync(file, 'original');
  assert.throws(() => v.writeJson(file, { replacement: true }));
  assert.equal(fs.readFileSync(file, 'utf8'), 'original');
});
test('captures reject old files, missing browser, timeout, missing output and old timestamps', () => {
  const output = temporary(), old = path.join(output, 'old.png');
  fs.writeFileSync(old, 'old-capture');
  assert.throws(() => v.capture('old.png', 'http://fixture.invalid', output, {
    spawn: () => { throw Error('Must not spawn'); },
  }));
  assert.equal(fs.readFileSync(old, 'utf8'), 'old-capture');
  for (const outcome of [{ status: null, error: { code: 'ENOENT' } },
    { status: null, error: { code: 'ETIMEDOUT' } }, { status: 1 }, { status: 0 }]) {
    assert.equal(v.capture('new.png', 'http://fixture.invalid', output, { spawn: () => outcome }).fresh, false);
  }
  const stale = v.capture('stale.png', 'http://fixture.invalid', output, { spawn: (browser, args) => {
    const file = args.find(a => a.startsWith('--screenshot=')).slice(13);
    fs.writeFileSync(file, Buffer.from('89504e470d0a1a0a', 'hex'));
    fs.utimesSync(file, new Date('2000-01-01'), new Date('2000-01-01'));
    return { status: 0 };
  } });
  assert.equal(stale.fresh, false);
  const dashboard = require('../../../../dashboards/event-service-met05.json');
  const content = '<main>' + [dashboard.title, ...dashboard.panels.map(p => p.title)].join('<h2>') + '</main>';
  const render = stdout => (browser, args) => {
    assert(args.includes('--dump-dom'));
    fs.writeFileSync(args.find(a => a.startsWith('--screenshot=')).slice(13), Buffer.from('89504e470d0a1a0a', 'hex'));
    return { status: 0, stdout };
  };
  const url = 'http://127.0.0.1:23000/d/event-service-met05';
  const success = v.capture('fresh.png', url, output, { spawn: render(content) });
  assert.equal(success.fresh, true);
  for (const [i, dom] of ['', '<h1>Sign in</h1>', '<h1>Dashboard not found</h1>',
    '<script>' + content + '</script>', content.replace('Backlog', 'Different panel'),
    content + '<p>Error loading data</p>', content + '<p>No data</p>'].entries()) {
    const name = 'invalid-' + i + '.png';
    assert.equal(v.capture(name, url, output, { spawn: render(dom) }).fresh, false);
    assert(!fs.existsSync(path.join(output, name)));
  }
  const trace = '0123456789abcdef';
  const traceContent = '<main>' + trace + ' event-service-api event-service-worker http_request process_reading</main>';
  for (const [i, dom] of [traceContent, traceContent.replace(trace, 'another'),
    traceContent.replace('process_reading', 'other'), traceContent + ' No traces found'].entries()) {
    assert.equal(v.capture('trace-' + i + '.png', 'http://127.0.0.1:26686/trace/' + trace,
      output, { spawn: render(dom) }).fresh, i === 0);
  }
  for (const [i, dom] of ['<main>event-service event-service-worker UP</main>',
    '<main>event-service event-service-worker DOWN</main>'].entries()) {
    assert.equal(v.capture('targets-' + i + '.png', 'http://127.0.0.1:29090/targets',
      output, { spawn: render(dom) }).fresh, i === 0);
  }
  const search = '<main>event-service-api http_request <a href="/trace/' + trace + '">Trace</a></main>';
  for (const [i, dom] of [search, search.replace('/trace/', '/other/')].entries()) {
    assert.equal(v.capture('search-' + i + '.png', 'http://127.0.0.1:26686/search?service=event-service-api',
      output, { spawn: render(dom) }).fresh, i === 0);
  }
});
test('CLI failures have nonzero exit and save failure evidence, without network/browser', () => {
  const temp = temporary(), preload = path.join(temp, 'offline.cjs');
  fs.writeFileSync(preload, "global.fetch=async()=>({status:404,json:async()=>({message:'offline fixture'})});require('child_process').spawnSync=()=>({status:null,error:{code:'ENOENT'}});");
  for (const script of ['05-verify.cjs', '06-screenshots.cjs']) {
    const output = path.join(temp, script);
    const result = cp.spawnSync(process.execPath, ['--require', preload, path.join(root, script), '--output', output]);
    assert.equal(result.status, 1);
    assert(fs.readdirSync(output).some(n => n.endsWith('.json')));
  }
});
test('PowerShell tunnel launcher uses only doubles, including failed startup and occupied ports', () => {
  const shell = process.platform === 'win32' ? 'powershell.exe' : 'pwsh';
  const result = cp.spawnSync(shell, ['-NoProfile', '-File', path.join(__dirname, 'transport.tests.ps1')],
    { encoding: 'utf8', timeout: 55000, windowsHide: true });
  assert.equal(result.status, 0, result.stdout + result.stderr);
});
test('real remote pipeline preserves missing/failed decoder and downstream failure', () => {
  const remote = fs.readFileSync(path.join(root, 'Invoke-Remote.ps1'), 'utf8')
    .match(/'(\bbash -o pipefail -c "[^"]+")'/)?.[1];
  assert(remote, 'Must explicitly start bash with pipefail');
  for (const [stub, payload, expected] of [
    ['base64() { return 23; }; export -f base64', 'cHJpbnRmIG9rCg==', 23],
    ['base64() { return 127; }; export -f base64', 'cHJpbnRmIG9rCg==', 127],
    ['', 'a', 1], ['', 'ZXhpdCA3Cg==', 7], ['', 'cHJpbnRmIG9rCg==', 0],
  ]) {
    const file = path.join(temporary(), 'pipeline.sh');
    fs.writeFileSync(file, stub + '\nprintf "%s" "' + payload + '" | ' + remote + '\n');
    const windows = process.platform === 'win32';
    const linuxPath = file.replaceAll('\\', '/').replace(/^([A-Z]):/i, (_, drive) => '/mnt/' + drive.toLowerCase());
    const result = cp.spawnSync(windows ? 'wsl.exe' : 'bash',
      windows ? ['--exec', 'bash', linuxPath] : [file], { encoding: 'utf8', timeout: 55000, windowsHide: true });
    assert.equal(result.status, expected, result.stdout + result.stderr);
  }
});

test('09 aborts a baseline Prometheus error before the generator can write readings', async () => {
  const originalFetch = global.fetch, originalSpawn = cp.spawn;
  const keys = [process.env.EVENT_PRODUCER_KEY, process.env.EVENT_ANALYST_KEY];
  let spawned = false;
  global.fetch = async url => body(url.includes('/v1/reception/counts') ?
    source.records.find(r => r.name === 'counts-global-before').body : { status: 'error' });
  cp.spawn = () => { spawned = true; throw Error('Generator must never start'); };
  process.env.EVENT_PRODUCER_KEY = 'fixture-producer';
  process.env.EVENT_ANALYST_KEY = 'fixture-analyst';
  try {
    await assert.rejects(require('../09-functional.cjs').run({ output: destination() }), /Prometheus status/);
    assert.equal(spawned, false);
  } finally {
    global.fetch = originalFetch; cp.spawn = originalSpawn;
    for (const [i, name] of ['EVENT_PRODUCER_KEY', 'EVENT_ANALYST_KEY'].entries()) {
      if (keys[i] === undefined) delete process.env[name]; else process.env[name] = keys[i];
    }
  }
});
test('10 records failed partial correlation without overwriting its source', async () => {
  const output = destination();
  await assert.rejects(require('../10-correlation.cjs').run({
    functional: path.join(root, '09-functional.json'), output,
  }, { fetcher: async () => body({ data: correlation.traces.slice(0, 9) }), sleep: async () => {} }));
  const failed = JSON.parse(fs.readFileSync(path.join(output, '10-correlation.json'), 'utf8'));
  assert.equal(failed.passed, false);
  assert.equal(failed.records.length, 12);
  assert(fs.readFileSync(path.join(root, '09-functional.json')).equals(sourceBytes));
});
test('Invoke-Remote propagates SSH failure and refuses an existing output directory', () => {
  const temp = temporary(), fixture = path.join(temp, 'harmless.sh'), wrapper = path.join(temp, 'remote.ps1');
  const output = path.join(temp, 'new-run');
  fs.writeFileSync(fixture, 'exit 0\n');
  const quote = s => "'" + s.replaceAll("'", "''") + "'";
  fs.writeFileSync(wrapper, "function ssh { if ($args[-1] -notlike '*bash -o pipefail*') { throw 'pipefail missing' }; Set-Variable -Name LASTEXITCODE -Value 23 -Scope 1; Write-Output 'fixture decoder failure' }\n& " +
    quote(path.join(root, 'Invoke-Remote.ps1')) + ' -ScriptFile ' + quote(fixture) +
    ' -LogName failed.txt -OutputDirectory ' + quote(output) + '\nexit $LASTEXITCODE\n');
  const shell = process.platform === 'win32' ? 'powershell.exe' : 'pwsh';
  const first = cp.spawnSync(shell, ['-NoProfile', '-File', wrapper], { encoding: 'utf8', timeout: 55000 });
  assert.equal(first.status, 23, first.stdout + first.stderr);
  const log = fs.readFileSync(path.join(output, 'failed.txt'));
  assert(log.toString('utf8').includes('EXIT_CODE=23') || log.toString('utf16le').includes('EXIT_CODE=23'));
  const second = cp.spawnSync(shell, ['-NoProfile', '-File', wrapper], { encoding: 'utf8', timeout: 55000 });
  assert.notEqual(second.status, 0);
  assert(fs.readFileSync(path.join(output, 'failed.txt')).equals(log));
});
test('Invoke-Remote rejects startup failures and missing exit codes instead of using stale success', () => {
  const shell = process.platform === 'win32' ? 'powershell.exe' : 'pwsh';
  const quote = s => "'" + s.replaceAll("'", "''") + "'";
  for (const stub of ["function ssh { throw 'cannot start SSH' }", "function ssh { Write-Output 'no process exit code' }",
    "function Get-Command { throw 'ssh not found' }"]) {
    const temp = temporary(), fixture = path.join(temp, 'harmless.sh'), wrapper = path.join(temp, 'remote.ps1');
    const output = path.join(temp, 'new-run');
    fs.writeFileSync(fixture, 'exit 0\n');
    fs.writeFileSync(wrapper, stub + '\n$global:LASTEXITCODE=0\n& ' + quote(path.join(root, 'Invoke-Remote.ps1')) +
      ' -ScriptFile ' + quote(fixture) + ' -LogName failed.txt -OutputDirectory ' + quote(output) + '\nexit $LASTEXITCODE\n');
    const result = cp.spawnSync(shell, ['-NoProfile', '-File', wrapper], { encoding: 'utf8', timeout: 55000 });
    assert.equal(result.status, 1, result.stdout + result.stderr);
    const log = fs.readFileSync(path.join(output, 'failed.txt'));
    assert(log.toString('utf8').includes('EXIT_CODE=1') || log.toString('utf16le').includes('EXIT_CODE=1'));
  }
});
test('delivery validation removes its temporary tools on success and early failure', () => {
  for (const fail of ['0', '7']) {
    const temp = temporary();
    const script = `
mktemp() { command mktemp -d "$TOOLS_TEST_ROOT/tools.XXXXXX"; }
curl() { return "$TOOLS_TEST_FAIL"; }
sha256sum() { cat >/dev/null; }
tar() {
  local tool=gitleaks
  [[ "$*" == *kubeconform* ]] && tool=kubeconform
  printf '#!/usr/bin/env bash\\nexit 0\\n' > "$tool"
  chmod +x "$tool"
}
export -f mktemp curl sha256sum tar
bash "$TOOLS_TEST_SCRIPT"
`;
    const result = cp.spawnSync('bash', ['-c', script], { encoding: 'utf8', env: {
      ...process.env, TOOLS_TEST_ROOT: temp, TOOLS_TEST_FAIL: fail,
      TOOLS_TEST_SCRIPT: path.join(root, '12-validate-delivery.sh'),
    } });
    assert.equal(result.status, Number(fail), result.stdout + result.stderr);
    assert.deepEqual(fs.readdirSync(temp), []);
  }
});
