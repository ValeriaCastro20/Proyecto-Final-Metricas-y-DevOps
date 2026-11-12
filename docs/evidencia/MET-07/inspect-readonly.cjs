// Read-only preparation snapshot. No mutation, load, credentials or arbitrary SSH commands.
const fs = require('node:fs');
const cp = require('node:child_process');
const assert = require('node:assert/strict');
const path = require('node:path');
const commands = {
  context: 'sudo -n k3s kubectl config current-context',
  deployment: 'sudo -n k3s kubectl --namespace eventos-development get deployment event-service-worker -o json',
  server_utc: 'date -u +%Y-%m-%dT%H:%M:%SZ',
};
function remote(command) {
  return new Promise(resolve => {
    cp.execFile('ssh', ['-F', 'NUL', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
      '-o', 'UpdateHostKeys=no', '-o', 'ConnectTimeout=8', '-o', 'IdentitiesOnly=yes',
      '-i', 'C:/Users/itsis/.ssh/id_ed25519',
      'azureuser@eventos-b97e31.mexicocentral.cloudapp.azure.com', command],
    { timeout: 12000, windowsHide: true, maxBuffer: 1000000 }, (error, stdout) => {
      resolve(error ? { connection_error: true, exit: typeof error.code === 'number' ? error.code : null } :
        { connection_error: false, exit: 0, value: stdout.trim() });
    });
  });
}
async function prom(endpoint) {
  const record = { endpoint, http: null, connection_error: false, server_date: null };
  try {
    const r = await fetch('http://127.0.0.1:29090' + endpoint, { redirect: 'error', signal: AbortSignal.timeout(8000) });
    record.http = r.status; record.server_date = r.headers.get('date');
    const b = await r.json();
    assert.equal(r.status, 200); assert.equal(b.status, 'success');
    record.data = endpoint.includes('/rules') ? { groups: b.data.groups.map(g => ({
      name: g.name, rules: g.rules.filter(x => x.name === 'HighEventBacklog').map(x => ({
        name: x.name, query: x.query, duration: x.duration, state: x.state, health: x.health,
        lastErrorPresent: Boolean(x.lastError), alerts: (x.alerts || []).map(a => ({state:a.state,labels:a.labels})),
      })),
    })).filter(g => g.rules.length) } : b.data;
  } catch { record.failed = true; record.connection_error = record.http === null; }
  return record;
}
(async () => {
  const file = process.argv[2];
  assert(file && !fs.existsSync(file), 'An unused evidence filename is required');
  const [context, deployment, server, rules, clock, backlog] = await Promise.all([
    remote(commands.context), remote(commands.deployment), remote(commands.server_utc),
    prom('/api/v1/rules'), prom('/api/v1/query?query=time%28%29'),
    prom('/api/v1/query?query=esc3_events_backlog_total%7Bjob%3D%22event-service%22%7D'),
  ]);
  const evidence = { type: 'REAL_READ_ONLY_PREPARATION', incident_executed: false, execution_authorized: false,
    isolation_verified: false, namespace: 'eventos-development', context, server,
    prometheus: { rules, clock, backlog }, deployment: { connection_error: deployment.connection_error, exit: deployment.exit } };
  if (!deployment.connection_error) {
    const d = JSON.parse(deployment.value);
    evidence.deployment = { ...evidence.deployment, uid: d.metadata.uid, resource_version: d.metadata.resourceVersion,
      replicas: d.spec.replicas, ready_replicas: d.status.readyReplicas,
      selector: d.spec.selector.matchLabels, template_labels: d.spec.template.metadata.labels,
      containers: d.spec.template.spec.containers.map(c => ({name:c.name,args:c.args,image:c.image})) };
  }
  const data = JSON.stringify(evidence, null, 2) + '\n';
  for (const key of [process.env.EVENT_PRODUCER_KEY, process.env.EVENT_ANALYST_KEY].filter(Boolean)) {
    assert(!data.includes(key), 'Credential detected; evidence not saved');
  }
  fs.writeFileSync(path.resolve(file), data, {flag:'wx'});
  console.log(JSON.stringify({file,incident_executed:false,context_read:!context.connection_error,
    deployment:evidence.deployment,rules_read:!rules.failed,alert_state:rules.data?.groups[0]?.rules[0]?.state}));
})().catch(e => { console.error(e.message); process.exitCode=1; });
