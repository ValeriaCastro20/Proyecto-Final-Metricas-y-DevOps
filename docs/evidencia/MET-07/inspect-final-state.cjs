const cp=require('node:child_process'),fs=require('node:fs'),assert=require('node:assert/strict');
const code = [
'import subprocess,json,datetime,os',
'from pathlib import Path',
'p=Path("/home/azureuser/met07-preflight-6d49dff7-65c8-4818-bcf4-5738b1e3569a")',
'd=json.loads(subprocess.check_output(["sudo","-n","k3s","kubectl","--context","default","--namespace","eventos-development","get","deployment/event-service-worker","-o","json"],text=True,timeout=15))',
'paths=[p,p/"evidence",*(p/"evidence").iterdir()]',
'print(json.dumps({"material":"REAL_READ_ONLY_FINAL_STATE","server_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"identity":{"uid":os.getuid(),"gid":os.getgid()},"worker":{"uid":d["metadata"]["uid"],"replicas":d["spec"]["replicas"],"ready":d["status"].get("readyReplicas"),"available":d["status"].get("availableReplicas")},"supervisor_file_times":{f.name:datetime.datetime.fromtimestamp(f.stat().st_mtime,datetime.timezone.utc).isoformat() for f in paths if f.is_file()},"private_modes":{str(f.relative_to(p)):{"uid":f.stat().st_uid,"gid":f.stat().st_gid,"mode":oct(f.stat().st_mode&0o777)} for f in paths},"incident_directory_exists":(p/"evidence"/"incident").exists(),"watchdog_probe_directory_exists":(p/"evidence"/"watchdog-probe").exists()}))'
].join('\n');
const r=cp.spawnSync('ssh',['-F','NUL','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UpdateHostKeys=no','-o','ConnectTimeout=10','-o','IdentitiesOnly=yes','-i','C:/Users/itsis/.ssh/id_ed25519','azureuser@eventos-b97e31.mexicocentral.cloudapp.azure.com','python3 -B -'],
{input:code,encoding:'utf8',timeout:25000,windowsHide:true});
if(r.status!==0){console.log(JSON.stringify({exit:r.status,stderr:r.stderr}));process.exit(1);}
for(const k of ['EVENT_PRODUCER_KEY','EVENT_ANALYST_KEY'])assert(!process.env[k]||!r.stdout.includes(process.env[k]));
const data=JSON.parse(r.stdout);assert.equal(data.worker.replicas,1);assert.equal(data.worker.ready,1);
fs.writeFileSync('docs/evidencia/MET-07/preflight-6d49dff7-65c8-4818-bcf4-5738b1e3569a/final-readonly-state.json',JSON.stringify(data,null,2)+'\n',{flag:'wx'});
console.log(r.stdout);
