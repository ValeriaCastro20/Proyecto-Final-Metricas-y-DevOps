// Explicitly read-only OS / independent watchdog inspection. No incident entry point or keys.
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const id='os-watchdog-'+crypto.randomUUID(),root='/home/azureuser/met07-'+id;
const base='docs/evidencia/MET-07';
function hashes(dir){const result={};for(const entry of fs.readdirSync(dir,{withFileTypes:true})){const name=path.join(dir,entry.name);if(entry.isDirectory())Object.assign(result,hashes(name));else if(entry.isFile())result[name]=crypto.createHash('sha256').update(fs.readFileSync(name)).digest('hex');}return result;}
const before=hashes(base),files={};
for(const name of ['met07.py','met07_os_watchdog_readonly.py'])files[name]=fs.readFileSync('scripts/'+name,'utf8');
const code=`import json,os,sys,time
from pathlib import Path
os.umask(0o077)
p=json.loads(${JSON.stringify(JSON.stringify({root,files}))})
r=Path(p['root']);r.mkdir(mode=0o700)
for name,data in p['files'].items():
 with (r/name).open('x',encoding='utf8') as f:f.write(data)
sys.path.insert(0,str(r))
import met07 as core,met07_os_watchdog_readonly as audit
e=core.Evidence(r/'evidence')
e.json('source-sha256.json',{n:__import__('hashlib').sha256(v.encode()).hexdigest() for n,v in p['files'].items()})
k=core.Kubernetes('default','eventos-development')
try:
 e.json('os-power-audit.json',audit.os_audit())
 initial=k.get();uid=initial['metadata']['uid']
 core.require(uid=='f1c9cafa-7fe9-4495-b806-94776f8a8326','Reviewed UID changed')
 state=k.preflight(uid);e.json('worker-preflight.json',state)
 result=audit.probe(e.root,state);e.json('independent-validation.json',result)
except BaseException as error:
 e.json('audit-failure.json',{'type':type(error).__name__,'reason':str(error) if isinstance(error,RuntimeError) else 'operation_failed','incident_executed':False})
finally:
 final=k.get();e.json('final-state.json',{'server_utc':core.utc(time.time()),'uid':final['metadata']['uid'],'replicas':final['spec']['replicas'],'ready':final['status'].get('readyReplicas'),'available':final['status'].get('availableReplicas'),'incident_executed':False,'load_attempts':0})
print(json.dumps({str(f.relative_to(e.root)):f.read_text() for f in e.root.rglob('*') if f.is_file()}))
`;
const result=cp.spawnSync('ssh',['-F','NUL','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UpdateHostKeys=no','-o','ConnectTimeout=15','-o','IdentitiesOnly=yes','-i','C:/Users/itsis/.ssh/id_ed25519','azureuser@eventos-b97e31.mexicocentral.cloudapp.azure.com','python3 -B -'],{input:code,encoding:'utf8',timeout:120000,windowsHide:true,maxBuffer:3000000});
assert.equal(result.status,0,'Read-only audit failed; preserve '+root);
for(const name of ['EVENT_PRODUCER_KEY','EVENT_ANALYST_KEY'])assert(!process.env[name]||!result.stdout.includes(process.env[name]));
const data=JSON.parse(result.stdout),after=hashes(base);assert.deepEqual(after,before,'Original evidence changed');
const local=path.join(base,id);fs.mkdirSync(local);
for(const [name,content] of Object.entries(data)){assert(!name.includes('..')&&!path.isAbsolute(name));const dest=path.join(local,name);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.writeFileSync(dest,content,{flag:'wx'});}
fs.writeFileSync(path.join(local,'original-evidence-sha256.json'),JSON.stringify({unchanged:true,files:before},null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({directory:local,remote_root:root,validation:JSON.parse(data['independent-validation.json']||'null'),failure:JSON.parse(data['audit-failure.json']||'null'),final:JSON.parse(data['final-state.json'])}));
