// Supplemental read-only diagnosis after the failed preflight. Never invokes Experiment or watchdog.
const fs=require('node:fs'), cp=require('node:child_process'), path=require('node:path'), assert=require('node:assert/strict');
const root='/home/azureuser/met07-preflight-6d49dff7-65c8-4818-bcf4-5738b1e3569a';
const local='docs/evidencia/MET-07/preflight-6d49dff7-65c8-4818-bcf4-5738b1e3569a';
const q=s=>{const a=String.fromCharCode(39),b=String.fromCharCode(34);return a+s.replaceAll(a,a+b+a+b+a)+a;};
const args=['-F','NUL','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UpdateHostKeys=no',
'-o','ConnectTimeout=10','-o','IdentitiesOnly=yes','-i','C:/Users/itsis/.ssh/id_ed25519','azureuser@eventos-b97e31.mexicocentral.cloudapp.azure.com'];
const code = [
'import sys,json,os,time',
'from pathlib import Path',
'sys.path.insert(0,sys.argv[1])',
'import met07 as core, met07_operate as op',
'p=json.load(sys.stdin)',
'os.umask(0o077)',
'e=core.Evidence(Path(sys.argv[1])/"diagnostics")',
'os.environ.update({k:p[k] for k in ("EVENT_PRODUCER_KEY","EVENT_ANALYST_KEY")})',
'k=core.Kubernetes("default","eventos-development")',
'd=k.get()',
'selected=json.loads(k.k("get","deployment","-l",core.SELECTOR,"-o","json"))["items"]',
'e.json("worker-selection.json",{"material":"REAL_READ_ONLY_DIAGNOSIS","server_utc":core.utc(time.time()),"identity":core.actor_identity(),"context":k.context,"namespace":k.namespace,"uid":d["metadata"]["uid"],"replicas":d["spec"]["replicas"],"ready":d["status"].get("readyReplicas"),"available":d["status"].get("availableReplicas"),"metadata_labels":d["metadata"].get("labels",{}),"template_labels":d["spec"]["template"]["metadata"]["labels"],"selector":d["spec"]["selector"]["matchLabels"],"deployment_selector_query_result":[{"name":x["metadata"]["name"],"uid":x["metadata"]["uid"]} for x in selected]})',
'e.json("endpoint-preflight.json",op.endpoint_checks(core.Http()))',
'e.json("power-preflight.json",op.power_check(p["power_review"],time.time()))',
'print(json.dumps({f.name:f.read_text() for f in e.root.iterdir() if f.is_file()}))'
].join('\n');
(async()=>{
const clock=cp.spawnSync('ssh',[...args,'date -u +%Y-%m-%dT%H:%M:%SZ'],{encoding:'utf8',timeout:15000,windowsHide:true});
assert.equal(clock.status,0);
const response=await fetch('https://api.github.com/repos/marchelo23/Proyecto-Final-Metricas-y-DevOps/actions/workflows/vm-power.yml/runs?per_page=20',{signal:AbortSignal.timeout(10000),redirect:'error'});
assert.equal(response.status,200);
const runs=(await response.json()).workflow_runs.map(r=>({id:r.id,status:r.status,conclusion:r.conclusion,event:r.event,created_at:r.created_at}));
const payload={EVENT_PRODUCER_KEY:process.env.EVENT_PRODUCER_KEY,EVENT_ANALYST_KEY:process.env.EVENT_ANALYST_KEY,
 power_review:{checked_server_utc:clock.stdout.trim(),next_stop_utc:'2026-11-13T05:00:00Z',azure_schedules_verified:false,
 active_power_workflows:runs.filter(r=>r.status!=='completed').length,workflow_runs:runs,
 azure_failure:'VM subscription e8293fad-4915-490d-b001-01575b97ed36 is not available to the authenticated Azure CLI account',
 no_automations_disabled:true,workflow_source_sha:'70dcb8a06a6bb592150c9c6dcf70fb18c5619a72'}};
const result=cp.spawnSync('ssh',[...args,'python3 -B -c '+q(code)+' '+q(root)],{input:JSON.stringify(payload),encoding:'utf8',timeout:90000,windowsHide:true,maxBuffer:1000000});
assert.equal(result.status,0,'Diagnosis failed; do not retry incident');
for(const value of [payload.EVENT_PRODUCER_KEY,payload.EVENT_ANALYST_KEY])assert(value&&!result.stdout.includes(value));
const files=JSON.parse(result.stdout),out=path.join(local,'diagnostics');
fs.mkdirSync(out);
for(const [name,data] of Object.entries(files)){assert.equal(path.basename(name),name);fs.writeFileSync(path.join(out,name),data,{flag:'wx'});}
console.log(JSON.stringify({material:'REAL_READ_ONLY_DIAGNOSIS',files:Object.keys(files),incident_executed:false}));
})().catch(()=>{console.error('Read-only diagnosis failed; preserve remote files and do not retry incident');process.exitCode=1;});
