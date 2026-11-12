const fs = require('node:fs');
const path = require('node:path');
const v = require('./verification.cjs');
async function run(options, { fetcher = fetch } = {}) {
  const dir = v.newDirectory(options.output), records = [];
  const result = { utc: new Date().toISOString(), records, passed: false };
  const get = (name, url, prometheus = false) => v.getJson(name, url, { records, prometheus, fetcher });
  try {
    await get('prometheus-ready', 'http://127.0.0.1:29090/api/v1/status/runtimeinfo', true);
    v.targets(await get('targets', 'http://127.0.0.1:29090/api/v1/targets', true));
    await get('rules', 'http://127.0.0.1:29090/api/v1/rules', true);
    const health = await get('grafana-health', 'http://127.0.0.1:23000/api/health');
    if (health.database !== 'ok') throw Error('Grafana database unhealthy');
    const datasource = await get('datasource', 'http://127.0.0.1:23000/api/datasources/uid/event-service-prometheus');
    const live = await get('provisioned-dashboard', 'http://127.0.0.1:23000/api/dashboards/uid/event-service-met05');
    const expected = JSON.parse(fs.readFileSync(path.join(__dirname, '../../../dashboards/event-service-met05.json'), 'utf8'));
    v.provisioned(live, expected, datasource);
    for (const p of expected.panels) {
      const q = encodeURIComponent(p.targets[0].expr);
      for (const [suffix, base] of [['prometheus', 'http://127.0.0.1:29090'],
        ['grafana-proxy', 'http://127.0.0.1:23000/api/datasources/proxy/uid/event-service-prometheus']]) {
        v.queryResult(await get('panel-' + p.id + '-' + suffix, base + '/api/v1/query?query=' + q, true));
      }
    }
    result.passed = true;
  } catch (error) { result.error = error.message; throw error; }
  finally { v.writeJson(path.join(dir, '05-verification.json'), result); }
  return result;
}
module.exports = { run };
v.cli({ filename: __filename, run });
