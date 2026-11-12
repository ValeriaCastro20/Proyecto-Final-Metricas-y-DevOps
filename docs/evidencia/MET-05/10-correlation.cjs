const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const v = require('./verification.cjs');
async function run(options, { fetcher = fetch, sleep } = {}) {
  if (!options.functional) throw Error('--functional required');
  const bytes = fs.readFileSync(options.functional), source = JSON.parse(bytes);
  const report = source.generator?.report;
  if (source.generator?.exitCode !== 0 || !report?.passed) throw Error('Generator must pass first');
  const rows = v.readingRows(source.records.find(r => r.name === 'readings-final')?.body, report.device_id);
  const dir = v.newDirectory(options.output), records = [];
  const result = { utc: new Date().toISOString(), source: path.basename(options.functional),
    sourceSha256: crypto.createHash('sha256').update(bytes).digest('hex'),
    device_id: report.device_id, originalFailure: source.error, records, passed: false };
  try {
    Object.assign(result, await v.waitForCorrelation(rows,
      (name, url) => v.getJson(name, url, { records, fetcher }), { sleep }));
    result.passed = true;
  } catch (error) { result.error = error.message; throw error; }
  finally { v.writeJson(path.join(dir, '10-correlation.json'), result); }
  return result;
}
module.exports = { run };
v.cli({ filename: __filename, run });
