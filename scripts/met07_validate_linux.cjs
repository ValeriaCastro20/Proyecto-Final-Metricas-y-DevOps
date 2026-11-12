const fs=require('node:fs'),cp=require('node:child_process'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const id='fixtures-'+crypto.randomUUID(),root='/home/azureuser/met07-'+id,files={};
for(const name of ['met07.py','met07_signals.py','met07_operate.py','met07_os_watchdog_readonly.py'])files['scripts/'+name]=fs.readFileSync('scripts/'+name,'utf8');
for(const name of fs.readdirSync('scripts/tests').filter(n=>n.includes('met07')&&n.endsWith('.py')))files['scripts/tests/'+name]=fs.readFileSync('scripts/tests/'+name,'utf8');
for(const name of ['kubernetes/resources.json','kubernetes/observability/k8-prometheus.yaml'])files[name]=fs.readFileSync(name,'utf8');
const code=`import json,os,subprocess,sys,hashlib
from pathlib import Path
os.umask(0o077)
p=json.loads(${JSON.stringify(JSON.stringify({root,files}))})
r=Path(p['root']);r.mkdir(mode=0o700)
for name,data in p['files'].items():
 f=r/name;f.parent.mkdir(mode=0o700,parents=True,exist_ok=True);f.write_text(data,encoding='utf8')
t=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(r/'scripts/tests'),'-p','test_met07*.py','-v'],cwd=r,capture_output=True,text=True,timeout=60)
result={'material':'LINUX_FIXTURES_NO_REAL_INCIDENT','exit':t.returncode,'stdout':t.stdout,'stderr':t.stderr,'source_sha256':{n:hashlib.sha256(v.encode()).hexdigest() for n,v in p['files'].items()}}
with (r/'fixture-validation.json').open('x') as f:json.dump(result,f)
print(json.dumps(result))
`;
const ssh=['-F','NUL','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UpdateHostKeys=no','-o','ConnectTimeout=15','-o','IdentitiesOnly=yes','-i','C:/Users/itsis/.ssh/id_ed25519','azureuser@eventos-b97e31.mexicocentral.cloudapp.azure.com','python3 -B -'];
const result=cp.spawnSync('ssh',ssh,{input:code,encoding:'utf8',timeout:90000,windowsHide:true,maxBuffer:2000000});assert.equal(result.status,0);
for(const name of ['EVENT_PRODUCER_KEY','EVENT_ANALYST_KEY'])assert(!process.env[name]||!result.stdout.includes(process.env[name]));
const data=JSON.parse(result.stdout),local='docs/evidencia/MET-07/'+id;fs.mkdirSync(local);fs.writeFileSync(local+'/fixture-validation.json',JSON.stringify(data,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify({directory:local,exit:data.exit,results:data.stderr}));process.exitCode=data.exit;
