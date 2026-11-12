// MET-07 safe preflight dispatch. No incident execution or retry.
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const ssh = ['-F','NUL','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UpdateHostKeys=no',
  '-o','ConnectTimeout=10','-o','IdentitiesOnly=yes','-i','C:/Users/itsis/.ssh/id_ed25519',
  'azureuser@eventos-b97e31.mexicocentral.cloudapp.azure.com'];
const quote = s => { const q=String.fromCharCode(39), d=String.fromCharCode(34); return q+s.replaceAll(q,q+d+q+d+q)+q; };
function remote(command, input, timeout=20000) {
  return cp.spawnSync('ssh', [...ssh,command], {input,encoding:'utf8',timeout,windowsHide:true,maxBuffer:2000000});
}
const python = code => 'python3 -B -c '+quote(code);
function safe(data) {
  for (const name of ['EVENT_PRODUCER_KEY','EVENT_ANALYST_KEY']) {
    const value=process.env[name];
    assert(value && !data.includes(value), 'Credential missing or detected in evidence');
  }
  return data;
}
(async()=>{
  const id='preflight-'+crypto.randomUUID();
  const remoteRoot='/home/azureuser/met07-'+id;
  const local=path.join('docs/evidencia/MET-07',id);
  assert(!fs.existsSync(local));
  const state=remote('sudo -n k3s kubectl --context default --namespace eventos-development get deployment event-service-worker -o json');
  assert.equal(state.status,0,'Cannot refresh worker');
  const d=JSON.parse(state.stdout);
  assert.equal(d.spec.replicas,1); assert.equal(d.status.readyReplicas,1);
  const clock=remote('date -u +%Y-%m-%dT%H:%M:%SZ');
  assert.equal(clock.status,0);
  const workflowResponse=await fetch('https://api.github.com/repos/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/workflows/vm-power.yml/runs?per_page=20',
    {redirect:'error',signal:AbortSignal.timeout(10000)});
  assert.equal(workflowResponse.status,200);
  const runs=(await workflowResponse.json()).workflow_runs.map(r=>({id:r.id,status:r.status,conclusion:r.conclusion,
    event:r.event,created_at:r.created_at,run_started_at:r.run_started_at}));
  const external={
    checked_server_utc:clock.stdout.trim(), next_stop_utc:'2026-11-13T05:00:00Z',
    azure_schedules_verified:false,
    azure_failure:'Actual VM subscription not present in authenticated Azure CLI account; ARM schedule list unavailable',
    active_power_workflows:runs.filter(r=>r.status!=='completed').length,
    workflow_source_sha:'70dcb8a06a6bb592150c9c6dcf70fb18c5619a72', workflow_runs:runs,
    no_automations_disabled:true
  };
  const files={};
  for(const name of ['met07.py','met07_signals.py','met07_operate.py']) {
    const data=fs.readFileSync(path.join('scripts',name),'utf8');
    safe(data);
    files[name]=data;
  }
  const bundle={root:remoteRoot,files};
  const install=remote(python('import json,os,sys; from pathlib import Path; os.umask(0o077); b=json.load(sys.stdin); p=Path(b["root"]); p.mkdir(mode=0o700); [(p.joinpath(n).write_text(v,encoding="utf8")) for n,v in b["files"].items()]; print("private_adapter_installed")'),JSON.stringify(bundle));
  assert.equal(install.status,0,'Remote adapter installation failed');
  const payload={
    EVENT_PRODUCER_KEY:process.env.EVENT_PRODUCER_KEY,EVENT_ANALYST_KEY:process.env.EVENT_ANALYST_KEY,
    authorization:{incident_authorized:true,isolated:true,isolation_review_ref:'User-exclusive-development-window-current-conversation',
      context:'default',namespace:'eventos-development',deployment_uid:d.metadata.uid},
    power_review:external,execute_once:false
  };
  // Credentials travel only in encrypted SSH stdin; never in arguments or a file.
  const execution=remote('python3 -B '+quote(remoteRoot+'/met07_operate.py')+' '+quote(remoteRoot+'/evidence'),JSON.stringify(payload),90000);
  fs.mkdirSync(local);
  const fetched=remote(python('import json,sys; from pathlib import Path; p=Path(sys.argv[1]); print(json.dumps({str(f.relative_to(p)):f.read_text() for f in p.rglob("*") if f.is_file()}))')+' '+quote(remoteRoot+'/evidence'),undefined,20000);
  assert.equal(fetched.status,0,'Evidence retrieval failed; preserve remote directory');
  const evidence=JSON.parse(safe(fetched.stdout));
  for(const [name,data] of Object.entries(evidence)) {
    assert(!name.includes('..') && !path.isAbsolute(name));
    const out=path.join(local,name);
    fs.mkdirSync(path.dirname(out),{recursive:true});
    fs.writeFileSync(out,safe(data),{flag:'wx'});
  }
  const after=remote('sudo -n k3s kubectl --context default --namespace eventos-development get deployment event-service-worker -o json');
  assert.equal(after.status,0);
  const final=JSON.parse(after.stdout);
  const result={material:'REAL_READ_ONLY_PREFLIGHT',base_commit:'24620b231ef246d203f7220090bdacd039c717f9',
    remote_root:remoteRoot,supervisor_exit:execution.status,supervisor_stdout:execution.stdout.trim(),
    supervisor_stderr_present:!!execution.stderr,
    incident_executed:false,load_attempts:0,device_writes:0,watchdog_executions:0,scale_mutations:0,
    producer_started:false,automatic_retry:false,
    worker:{uid:final.metadata.uid,replicas:final.spec.replicas,ready:final.status.readyReplicas,
      available:final.status.availableReplicas,resource_version:final.metadata.resourceVersion},
    source_sha256:Object.fromEntries(Object.entries(files).map(([n,v])=>[n,crypto.createHash('sha256').update(v).digest('hex')]))
  };
  assert.equal(final.metadata.uid,d.metadata.uid); assert.equal(final.spec.replicas,1); assert.equal(final.status.readyReplicas,1);
  assert(evidence['adapter-failure.json'],'Unexpected preflight result; do not execute automatically');
  assert(!Object.keys(evidence).some(n=>n.startsWith('incident/') || n.startsWith('watchdog-probe/')));
  fs.writeFileSync(path.join(local,'dispatch-result.json'),safe(JSON.stringify(result,null,2)+'\n'),{flag:'wx'});
  console.log(JSON.stringify({directory:local,remote_root:remoteRoot,supervisor_exit:execution.status,incident_executed:false,worker:result.worker}));
})().catch(()=>{console.error('Safe dispatch failed; do not retry incident. Preserve remote evidence.');process.exitCode=1;});
