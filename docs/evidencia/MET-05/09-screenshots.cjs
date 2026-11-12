const fs = require('node:fs');
const v = require('./verification.cjs');
async function run(options, dependencies) {
  if (!options.functional || !options.correlation) throw Error('--functional and --correlation required');
  const bytes = fs.readFileSync(options.functional);
  const source = JSON.parse(bytes), correlation = JSON.parse(fs.readFileSync(options.correlation, 'utf8'));
  const { rows, trace } = v.sameRun(source, correlation, bytes);
  const window = v.serverWindow(rows);
  const dir = v.newDirectory(options.output);
  v.captures([
    ['09-grafana-functional.png', 'http://127.0.0.1:23000/d/event-service-met05?orgId=1&from=' +
      (window.start / 1000) + '&to=' + (window.end / 1000) + '&kiosk'],
    ['09-jaeger-correlated.png', 'http://127.0.0.1:26686/trace/' + trace],
  ], dir, dependencies);
}
module.exports = { run };
v.cli({ filename: __filename, run });
