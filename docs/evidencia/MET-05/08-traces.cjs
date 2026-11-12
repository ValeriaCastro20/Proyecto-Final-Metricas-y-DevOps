const path = require('node:path');
const v = require('./verification.cjs');
async function run(options) {
  const dir = v.newDirectory(options.output), records = [];
  const result = { utc: new Date().toISOString(), records, passed: false };
  try {
    for (const service of ['event-service-api', 'event-service-worker']) {
      const body = await v.getJson(service, 'http://127.0.0.1:26686/api/traces?service=' + service + '&limit=20');
      if (body.errors?.length) throw Error('Jaeger query errors');
      records.push({ service, traces: v.safeTraces(body.data) });
    }
    result.passed = true; // Enumeration only; does not assert business correlation.
  } catch (error) { result.error = error.message; throw error; }
  finally { v.writeJson(path.join(dir, '08-traces.json'), result); }
}
module.exports = { run };
v.cli({ filename: __filename, run });
