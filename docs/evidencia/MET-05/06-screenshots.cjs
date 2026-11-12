const v = require('./verification.cjs');
async function run(options, dependencies) {
  const dir = v.newDirectory(options.output);
  v.captures([
    ['grafana-dashboard.png', 'http://127.0.0.1:23000/d/event-service-met05?orgId=1&from=now-30m&to=now&kiosk'],
    ['prometheus-targets.png', 'http://127.0.0.1:29090/targets'],
    ['jaeger-traces.png', 'http://127.0.0.1:26686/search?service=event-service-api&limit=20&lookback=1h'],
  ], dir, dependencies);
}
module.exports = { run };
v.cli({ filename: __filename, run });
