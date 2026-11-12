const fs=require('fs');
const path=require('path');
const {spawn}=require('child_process');
const assert=require('assert/strict');
const dir=__dirname, base='http://127.0.0.1:28000', prom='http://127.0.0.1:29090', graf='http://127.0.0.1:23000', jaeger='http://127.0.0.1:26686';
const evidence={started:new Date().toISOString(),scope:'MET-05; eventos-development; worker remains active',records:[]};
const secrets=[process.env.EVENT_PRODUCER_KEY,process.env.EVENT_ANALYST_KEY].filter(Boolean);
function save(){const data=JSON.stringify(evidence,null,2)+'\n';if(secrets.some(k=>data.includes(k)))throw Error('Credential detected: evidence not written');fs.writeFileSync(path.join(dir,'09-functional.json'),data);}
async function get(name,url,auth=false){const r=await fetch(url,{redirect:'error',headers:auth?{'X-API-Key':process.env.EVENT_ANALYST_KEY}:{},signal:AbortSignal.timeout(15000)});assert.equal(r.status,200,name+' HTTP');const body=await r.json();evidence.records.push({name,url,http:r.status,utc:new Date().toISOString(),body});return body;}
async function query(name,q,server=prom){return get(name,server+'/api/v1/query?query='+encodeURIComponent(q));}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{try{
assert.equal(secrets.length,2,'Both credentials required');
const before=await get('counts-global-before',base+'/v1/reception/counts',true);
for(const q of ['esc3_events_received_total','esc3_events_processed_total','esc3_events_backlog_total','esc3_processor_duration_seconds_count'])await query('baseline-'+q,q);
const run='met05-'+new Date().toISOString().replace(/[-:.TZ]/g,'')+'-'+require('crypto').randomBytes(3).toString('hex');
evidence.command='cargo +1.97.1-x86_64-pc-windows-msvc run --locked --example scenario_load -- custom --count 10 --rate 1 --invalid 0 --duplicates 0 --late 0 --seed 3 --run '+run;
evidence.run=run;
evidence.binary={path:'target/debug/examples/scenario_load.exe',sha256:require('crypto').createHash('sha256').update(fs.readFileSync('target/debug/examples/scenario_load.exe')).digest('hex'),rust:'1.97.1-x86_64-pc-windows-msvc',sourceCommit:'eb8fa8fcfdccab1f9879e9acc1128a9b974d4933'};
const result=await new Promise((resolve,reject)=>{const child=spawn(path.resolve('target/debug/examples/scenario_load.exe'),['custom','--count','10','--rate','1','--invalid','0','--duplicates','0','--late','0','--seed','3','--run',run],{env:{...process.env,ESC3_BASE_URL:base},windowsHide:true});let out='',err='';child.stdout.on('data',b=>out+=b);child.stderr.on('data',b=>err+=b);child.on('error',reject);child.on('close',code=>resolve({code,out,err}));});
evidence.generator={exitCode:result.code,report:JSON.parse(result.out)};
assert.equal(result.code,0,'generator exit');const report=evidence.generator.report;assert.equal(report.passed,true);assert.deepEqual(report.statuses,{'202':10});
const device=report.device_id;let counts;
for(let i=0;i<30;i++){counts=await get('counts-device-poll',base+'/v1/reception/counts?device_id='+device,true);if(counts.processed===10&&counts.pending===0)break;await sleep(1000);}
assert.equal(counts.accepted,10);assert.equal(counts.processed,10);assert.equal(counts.pending,0);
const rows=await get('readings-final',base+'/v1/devices/'+device+'/readings?from=2040-01-01T00:00:00Z&to=2041-01-01T00:00:00Z&limit=100',true);
assert.equal(rows.length,10);assert(rows.every(r=>r.processed_at));
await get('statistics-final',base+'/v1/devices/'+device+'/statistics?from=2040-01-01T00:00:00Z&to=2041-01-01T00:00:00Z',true);
const after=await get('counts-global-after',base+'/v1/reception/counts',true);assert.equal(after.pending,0);evidence.globalDelta=Object.fromEntries(Object.keys(after).map(k=>[k,after[k]-before[k]]));
await sleep(20000);
const targets=await get('targets-final',prom+'/api/v1/targets');assert(targets.data.activeTargets.filter(t=>['event-service','event-service-worker'].includes(t.labels.job)).every(t=>t.health==='up'));
await get('rules-final',prom+'/api/v1/rules');
const dashboard=await get('dashboard-final',graf+'/api/dashboards/uid/event-service-met05');assert.equal(dashboard.meta.provisioned,true);assert.equal(dashboard.dashboard.panels.length,8);
for(const panel of dashboard.dashboard.panels){const q=panel.targets[0].expr;for(const [suffix,server] of [['prometheus',prom],['grafana',graf+'/api/datasources/proxy/uid/event-service-prometheus']]){const a=await query('panel-'+panel.id+'-'+suffix,q,server);assert.equal(a.status,'success');assert(a.data.result.length>0,'panel '+panel.id+' has series');assert(a.data.result.some(s=>Number.isFinite(Number(s.value[1]))),'panel '+panel.id+' has finite observation (other NaN series preserved)');}}
for(const q of ['esc3_events_received_total','esc3_events_processed_total','esc3_events_backlog_total','esc3_processor_duration_seconds_count'])await query('final-'+q,q);
const ids=new Set(rows.map(r=>r.id));let matches=[];
for(let attempt=0;attempt<12;attempt++){
const r=await fetch(jaeger+'/api/traces?service=event-service-worker&operation=process_reading&limit=100&start='+Math.floor(Date.parse(evidence.started)*1000),{signal:AbortSignal.timeout(15000)});assert.equal(r.status,200);const data=await r.json();
matches=(data.data||[]).filter(t=>t.spans.some(s=>s.operationName==='process_reading'&&s.tags.some(k=>k.key==='reading_id'&&ids.has(k.value)))).map(t=>({traceID:t.traceID,processes:Object.fromEntries(Object.entries(t.processes).map(([k,v])=>[k,{serviceName:v.serviceName}])),spans:t.spans.map(s=>({spanID:s.spanID,operationName:s.operationName,processID:s.processID,startTime:s.startTime,duration:s.duration,references:s.references,tags:s.tags.filter(k=>['reading_id','component','route','status','otel.kind'].includes(k.key))}))}));
if(matches.some(t=>t.spans.some(w=>w.operationName==='process_reading'&&w.references.some(ref=>ref.refType==='CHILD_OF'&&ref.traceID===t.traceID&&t.spans.some(a=>a.spanID===ref.spanID&&a.operationName==='http_request'&&a.tags.some(k=>k.key==='route'&&k.value==='/v1/readings'))))))break;await sleep(5000);
}
evidence.correlatedTraces=matches;
assert(matches.some(t=>t.spans.some(w=>w.operationName==='process_reading'&&w.references.some(ref=>ref.refType==='CHILD_OF'&&ref.traceID===t.traceID&&t.spans.some(a=>a.spanID===ref.spanID&&a.operationName==='http_request'&&a.tags.some(k=>k.key==='route'&&k.value==='/v1/readings'))))),'API to worker parent correlation');
evidence.passed=true;console.log(JSON.stringify({device,counts,globalDelta:evidence.globalDelta,correlatedTraces:matches.map(t=>t.traceID),passed:true},null,2));
}catch(e){evidence.passed=false;evidence.error=e.message;console.error(e.message);process.exitCode=1;}finally{evidence.finished=new Date().toISOString();save();}})();