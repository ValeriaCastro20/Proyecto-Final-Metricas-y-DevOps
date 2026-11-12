// Operational one-shot dispatcher. Installs reviewed sources, then starts the Linux window-gated launcher.
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const evidence="docs/evidencia/MET-07/power-workflow-correction-4dc99f52-4bae-4b31-b19f-5b6b5c91d351";
const root='/home/azureuser/met07-operational-'+crypto.randomUUID();
const ssh=['-F','NUL','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UpdateHostKeys=no','-o','ConnectTimeout=15','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3','-o','IdentitiesOnly=yes','-i','C:/Users/itsis/.ssh/id_ed25519','azureuser@eventos-b97e31.mexicocentral.cloudapp.azure.com'];
const quote=s=>"'"+s.replaceAll("'","'\"'\"'")+"'";
const files={};for(const name of ['met07.py','met07_operate.py','met07_signals.py','met07_launch.py'])files[name]=fs.readFileSync('scripts/'+name,'utf8');
const hashes=Object.fromEntries(Object.entries(files).map(([n,s])=>[n,crypto.createHash('sha256').update(s).digest('hex')]));
const original=JSON.parse(fs.readFileSync(evidence+'/original-evidence-sha256.json','utf8')).files;
function verifyOriginal(){for(const entry of original)assert.equal(crypto.createHash('sha256').update(fs.readFileSync(entry.path)).digest('hex'),entry.sha256,entry.path);}
function safe(text){for(const name of ['EVENT_PRODUCER_KEY','EVENT_ANALYST_KEY'])assert(process.env[name]&&!String(text).includes(process.env[name]),'Credential absent or present in evidence');return text;}
(async()=>{
verifyOriginal();assert(!fs.existsSync(evidence+'/dispatch-start.json'),'This operational dispatcher has already been invoked; never retry automatically');
const bundle={root,files};
const install=`import json,os,sys\nfrom pathlib import Path\nos.umask(0o077)\np=json.load(sys.stdin);r=Path(p['root']);r.mkdir(mode=0o700)\nfor n,s in p['files'].items():\n with (r/n).open('x',encoding='utf8') as f:f.write(s)\nprint('private_sources_installed')\n`;
const installed=cp.spawnSync('ssh',[...ssh,'python3 -B -c '+quote(install)],{input:JSON.stringify(bundle),encoding:'utf8',timeout:25000,windowsHide:true});assert.equal(installed.status,0,'Installation failed; preserve '+root);
const payload={execute_once:true,administrator_confirmation:JSON.parse(fs.readFileSync(evidence+'/administrator-confirmation.json','utf8')),
 authorization:{incident_authorized:true,isolated:true,isolation_review_ref:'User accepted administrator window and reconfirmed exclusive eventos-development incident in this conversation',context:'default',namespace:'eventos-development',deployment_uid:'f1c9cafa-7fe9-4495-b806-94776f8a8326'},source_sha256:hashes,
 EVENT_PRODUCER_KEY:process.env.EVENT_PRODUCER_KEY,EVENT_ANALYST_KEY:process.env.EVENT_ANALYST_KEY};
for(const name of ['EVENT_PRODUCER_KEY','EVENT_ANALYST_KEY'])assert(payload[name]);
fs.writeFileSync(evidence+'/dispatch-start.json',safe(JSON.stringify({remote_root:root,source_sha256:hashes,execute_once:true,arm_query_performed:false,window_start:'2026-11-12T21:00:00Z',window_end:'2026-11-12T23:00:00Z',automatic_retry:false},null,2)+'\n'),{flag:'wx'});
console.log(JSON.stringify({phase:'operational_launcher_started_window_gated',remote_root:root}));
const execution=await new Promise((resolve,reject)=>{
 const child=cp.spawn('ssh',[...ssh,'python3 -B '+quote(root+'/met07_launch.py')+' '+quote(root)],{windowsHide:true,stdio:['pipe','pipe','pipe']});let buffer='',stderrPresent=false;
 child.stdout.setEncoding('utf8');child.stdout.on('data',data=>{buffer+=data;let split;while((split=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,split);buffer=buffer.slice(split+1);if(line.trim()){const record=JSON.parse(safe(line));assert(['waiting_authorized_window','single_incident_entered','failed_no_automatic_retry'].includes(record.phase));console.log(JSON.stringify(record));}}});
 child.stderr.on('data',()=>{stderrPresent=true;});child.on('error',reject);child.on('close',(code,signal)=>resolve({exit:code,signal,stderr_present:stderrPresent}));child.stdin.end(JSON.stringify(payload));
});
const collect=`import json,sys\nfrom pathlib import Path\nr=Path(sys.argv[1]);e=r/'evidence'\nprint(json.dumps({str(f.relative_to(e)):f.read_text() for f in e.rglob('*') if f.is_file()}))\n`;
const fetched=cp.spawnSync('ssh',[...ssh,'python3 -B -c '+quote(collect)+' '+quote(root)],{encoding:'utf8',timeout:30000,windowsHide:true,maxBuffer:16000000});assert.equal(fetched.status,0,'Evidence retrieval failed; preserve remote '+root);
const records=JSON.parse(safe(fetched.stdout));const local=evidence+'/execution';fs.mkdirSync(local);
for(const [name,data] of Object.entries(records)){assert(!name.includes('..')&&!path.isAbsolute(name));const file=path.join(local,name);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,safe(data),{flag:'wx'});}
verifyOriginal();fs.writeFileSync(evidence+'/dispatch-result.json',safe(JSON.stringify({remote_root:root,...execution,source_sha256:hashes,original_hashes_unchanged:true,automatic_retry:false},null,2)+'\n'),{flag:'wx'});
console.log(JSON.stringify({phase:'evidence_retrieved',directory:local,...execution}));process.exitCode=execution.exit===0?0:1;
})().catch(error=>{console.error('Operational dispatch stopped; never retry incident automatically. Preserve remote evidence. '+safe(error.message));process.exitCode=1;});
