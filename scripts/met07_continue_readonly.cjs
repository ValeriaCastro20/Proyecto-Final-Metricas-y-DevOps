// Read-only continuation: fresh private evidence, four temporary forwards, no incident entry point.
const fs=require('node:fs'),cp=require('node:child_process'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const ssh=['-F','NUL','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UpdateHostKeys=no','-o','ConnectTimeout=15','-o','IdentitiesOnly=yes','-i','C:/Users/itsis/.ssh/id_ed25519','azureuser@eventos-b97e31.mexicocentral.cloudapp.azure.com'];
const remote=code=>cp.spawnSync('ssh',[...ssh,'python3 -B -'],{input:code,encoding:'utf8',timeout:180000,windowsHide:true,maxBuffer:4000000});
(async()=>{
const id='continuation-'+crypto.randomUUID(),root='/home/azureuser/met07-'+id;
const files={};
for(const name of ['met07.py','met07_signals.py','met07_operate.py','met07_os_watchdog_readonly.py'])files['scripts/'+name]=fs.readFileSync('scripts/'+name,'utf8');
for(const name of fs.readdirSync('scripts/tests').filter(n=>n.includes('met07')&&n.endsWith('.py')))files['scripts/tests/'+name]=fs.readFileSync('scripts/tests/'+name,'utf8');
for(const name of ['kubernetes/resources.json','kubernetes/observability/k8-prometheus.yaml'])files[name]=fs.readFileSync(name,'utf8');
const base='https://api.github.com/repos/marchelo23/Proyecto-Final-Metricas-y-DevOps';
async function get(url){const r=await fetch(url,{redirect:'error',signal:AbortSignal.timeout(15000)});assert.equal(r.status,200);return r.json();}
const workflow=await get(base+'/contents/.github/workflows/vm-power.yml?ref=main');
const source=Buffer.from(workflow.content,'base64').toString('utf8');assert(source.includes("cron: '0 5 * * *'"));
const active=[];
for(const status of ['queued','in_progress','waiting','pending','requested']){
 for(let page=1;;page++){const r=await get(base+'/actions/workflows/vm-power.yml/runs?status='+status+'&per_page=100&page='+page);active.push(...r.workflow_runs.map(x=>({id:x.id,status:x.status,event:x.event,created_at:x.created_at})));if(r.workflow_runs.length<100)break;assert(page<20);}
}
const arm=cp.spawnSync('az.cmd',['rest','--method','get','--url','https://management.azure.com/subscriptions/e8293fad-4915-490d-b001-01575b97ed36/providers/Microsoft.DevTestLab/schedules?api-version=2018-09-15','--query','value[].{id:id,status:properties.status,target:properties.targetResourceId}','-o','json'],{encoding:'utf8',timeout:30000,windowsHide:true,shell:true});
// A failed/empty ARM process never verifies schedules.
const armVerified=arm.status===0&&arm.stdout.trim().startsWith('[')&&JSON.parse(arm.stdout).length===0;
const payload={root,files,authorization:{incident_authorized:true,isolated:true,isolation_review_ref:'User reconfirmed exclusive eventos-development window in current conversation; technical conditions refreshed separately'},external:{azure_schedules_verified:armVerified,azure_cli_exit:arm.status,azure_failure:armVerified?null:'ARM schedule access not verified for actual VM subscription',active_power_workflows:active.length,workflow_runs:active,workflow_source_sha:workflow.sha,no_automations_disabled:true},keys:{EVENT_PRODUCER_KEY:process.env.EVENT_PRODUCER_KEY,EVENT_ANALYST_KEY:process.env.EVENT_ANALYST_KEY}};
for(const value of Object.values(payload.keys))assert(value);
const code=`import json,os,sys,subprocess,time,datetime,socket
from pathlib import Path
os.umask(0o077)
p=json.loads(${JSON.stringify(JSON.stringify(payload))})
root=Path(p['root']);root.mkdir(mode=0o700)
for name,data in p['files'].items():
 f=root/name;f.parent.mkdir(mode=0o700,parents=True,exist_ok=True);f.write_text(data,encoding='utf8')
sys.path.insert(0,str(root/'scripts'))
import met07 as core,met07_operate as op
e=core.Evidence(root/'evidence')
os.environ.update(p.pop('keys'))
e.json('source-sha256.json',{n:__import__('hashlib').sha256(v.encode()).hexdigest() for n,v in p['files'].items()})
e.json('authorization.json',p['authorization'])
tests=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(root/'scripts/tests'),'-p','test_met07*.py','-v'],cwd=root,capture_output=True,text=True,timeout=60)
e.json('fixture-validation.json',{'material':'LINUX_FIXTURES_NO_REAL_INCIDENT','exit':tests.returncode,'stdout':tests.stdout,'stderr':tests.stderr})
k=core.Kubernetes('default','eventos-development');initial=k.get();uid=initial['metadata']['uid']
core.require(uid=='f1c9cafa-7fe9-4495-b806-94776f8a8326','Reviewed UID changed')
children=[];collector=None
try:
 state=k.preflight(uid);e.json('worker-preflight.json',state)
 ports=[('event-service',28000,8000),('prometheus',29090,9090),('jaeger-collector',26686,16686),('grafana',23000,3000)]
 for service,local,target in ports:
  with socket.socket() as s:s.bind(('127.0.0.1',local))
  log=open(root/(service+'-forward.log'),'x')
  args=['sudo','-n','k3s','kubectl','--context','default','--namespace','eventos-development','--request-timeout=3s','port-forward','--address=127.0.0.1','service/'+service,str(local)+':'+str(target)]
  child=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True);children.append((service,local,child,log))
 deadline=time.monotonic()+15
 while True:
  ready=True
  for service,port,child,log in children:
   core.require(child.poll() is None,'Forward exited: '+service)
   try:
    with socket.create_connection(('127.0.0.1',port),timeout=.2):pass
   except OSError:ready=False
  if ready:break
  core.require(time.monotonic()<deadline,'Forward readiness timeout');time.sleep(.2)
 endpoints=op.endpoint_checks(core.Http());e.json('endpoint-preflight.json',endpoints)
 e.json('forward-transports.json',{'material':'REAL_LOOPBACK_FORWARDS','services':[{'service':s,'port':port,'pid':c.pid,'alive':c.poll() is None} for s,port,c,l in children]})
 now=datetime.datetime.now(datetime.timezone.utc);nextstop=now.replace(hour=5,minute=0,second=0,microsecond=0)
 if nextstop<=now:nextstop+=datetime.timedelta(days=1)
 external=p['external'];external.update(checked_server_utc=core.utc(time.time()),next_stop_utc=nextstop.isoformat())
 power=op.power_check(external,time.time());e.json('power-preflight.json',power)
 if endpoints['passed']:
  baseline=core.Http().snapshot(k.namespace);e.json('baseline.json',baseline)
  collector=op.VerifiedCollector(k,core.Http(),uid,'met07-readiness-only',mode='real-read-only')
  collector.start_follow(baseline['server_utc'],e);collector.verify_live()
 e.json('decision.json',{'incident_executed':False,'scale_mutations':0,'device_writes':0,'load_attempts':0,'watchdog_executions':0,'power_passed':power['passed'],'endpoints_passed':endpoints['passed'],'fixture_exit':tests.returncode,'watchdog_verified':False,'reason':'Diagnostic-only continuation; incident requires all preconditions and real guard probe'})
except BaseException as error:
 e.json('diagnostic-failure.json',{'type':type(error).__name__,'reason':str(error) if isinstance(error,RuntimeError) else 'operation_failed','incident_executed':False})
finally:
 if collector:collector.stop_follow()
 for service,port,child,log in children:
  child.terminate()
  try:child.wait(timeout=5)
  except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
  log.close()
 final=k.get();e.json('final-state.json',{'material':'REAL_READ_ONLY_STATE','server_utc':core.utc(time.time()),'uid':final['metadata']['uid'],'replicas':final['spec']['replicas'],'ready':final['status'].get('readyReplicas'),'available':final['status'].get('availableReplicas'),'temporary_forwards_stopped':all(c.poll() is not None for s,port,c,l in children)})
 core.require(final['metadata']['uid']==uid and final['spec']['replicas']==1 and final['status'].get('readyReplicas')==1,'Final worker check failed')
print(json.dumps({f.name:f.read_text() for f in e.root.iterdir() if f.is_file()}))
`;
const result=remote(code);assert.equal(result.status,0,'Remote diagnosis failed; preserve '+root);
for(const value of Object.values(payload.keys))assert(!result.stdout.includes(value),'Credential detected');
const evidence=JSON.parse(result.stdout),local='docs/evidencia/MET-07/'+id;fs.mkdirSync(local);
for(const [name,data] of Object.entries(evidence)){assert.equal(require('node:path').basename(name),name);fs.writeFileSync(local+'/'+name,data,{flag:'wx'});}
console.log(JSON.stringify({directory:local,remote_root:root,files:Object.keys(evidence),decision:JSON.parse(evidence['decision.json']||'null'),final:JSON.parse(evidence['final-state.json'])}));
})().catch(error=>{console.error('Continuation failed: '+error.message);process.exitCode=1;});
