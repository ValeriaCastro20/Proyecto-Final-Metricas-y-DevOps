const fs=require('fs');const path=require('path');const dir=__dirname;const records=[];
async function get(name,url){const response=await fetch(url,{signal:AbortSignal.timeout(15000)});const body=await response.json();const record={name,url,http:response.status,body};records.push(record);console.log(name+' HTTP='+response.status);return body;}
(async()=>{try{
await get('prometheus-ready','http://127.0.0.1:29090/api/v1/status/runtimeinfo');
await get('targets','http://127.0.0.1:29090/api/v1/targets');
await get('rules','http://127.0.0.1:29090/api/v1/rules');
await get('grafana-health','http://127.0.0.1:23000/api/health');
await get('datasource','http://127.0.0.1:23000/api/datasources/uid/event-service-prometheus');
const live=await get('provisioned-dashboard','http://127.0.0.1:23000/api/dashboards/uid/event-service-met05');
const expected=JSON.parse(fs.readFileSync(path.join(dir,'../../../dashboards/event-service-met05.json'),'utf8'));
console.log('DASHBOARD_PANEL_COUNT='+live.dashboard?.panels?.length); console.log('PROVISIONED='+live.meta?.provisioned);
for(const p of expected.panels){const q=encodeURIComponent(p.targets[0].expr);const a=await get('panel-'+p.id+'-prometheus','http://127.0.0.1:29090/api/v1/query?query='+q); console.log(p.title+' SERIES='+a.data?.result?.length+' STATUS='+a.status);const b=await get('panel-'+p.id+'-grafana-proxy','http://127.0.0.1:23000/api/datasources/proxy/uid/event-service-prometheus/api/v1/query?query='+q);console.log('GRAFANA_PROXY_SERIES='+b.data?.result?.length+' STATUS='+b.status);}
await get('jaeger-services','http://127.0.0.1:26686/api/services');
const response=await fetch('http://127.0.0.1:26686/api/traces?service=event-service-api&limit=10',{signal:AbortSignal.timeout(15000)});const traces=await response.json();
const summary={name:'jaeger-traces-safe-summary',http:response.status,traces:(traces.data||[]).map(t=>({traceID:t.traceID,services:Object.values(t.processes).map(p=>p.serviceName),spans:t.spans.map(s=>({spanID:s.spanID,operationName:s.operationName,processID:s.processID,references:s.references,tags:s.tags.filter(t=>['component','route','status','otel.kind'].includes(t.key))}))}))};records.push(summary);console.log(JSON.stringify(summary));
}finally{fs.writeFileSync(path.join(dir,'05-verification.json'),JSON.stringify({utc:new Date().toISOString(),records},null,2)+'\n');}})().catch(e=>{console.error(e);process.exitCode=1;});
