// Real n8n CLI execution, immutable S01-S10 test fixtures ONLY.
// No arbitrary workflow inputs, node code, URLs, HTTP requests, or credentials from clients.
import { createServer } from 'node:http';
import { execFile } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
const PORT=Number(process.env.PORT||3001);
const ORIGIN='https://procureflow-n8n-native-canvas-production.up.railway.app';
const N8N_BIN='/usr/local/bin/n8n';
const VALID=/^S(0[1-9]|10)$/;
const results=new Map();
let busy=false,lastStarted=0;
function send(res,status,body) {
  res.writeHead(status,{
    'Content-Type':'application/json; charset=utf-8',
    'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
    'Access-Control-Allow-Origin':ORIGIN,
    'Vary':'Origin'
  });res.end(JSON.stringify(body));
}
async function runN8n(id) {
  const workflowId='PFDEMO2026'+id+'WF';
  return await new Promise((resolve,reject)=>{
    execFile(N8N_BIN,['execute','--id',workflowId],
      {timeout:75000,maxBuffer:12*1024*1024,env:{...process.env,N8N_DIAGNOSTICS_ENABLED:'false'}},
      async (error,stdout,stderr)=>{
        const raw=(stdout||'')+'\n'+(stderr||'');
        const success=!error && /"executionStatus":\s*"success"/.test(raw);
        const errorMessage=error?String(error.message).slice(0,350):null;
        // Parse actual n8n CLI runData, not arbitrary nested JSON field names.
        function getRunData(text){
          const marker=/"runData"\s*:\s*\{/.exec(text);
          if(!marker)return null;
          const start=text.indexOf('{',marker.index);
          let depth=0,inString=false,escape=false;
          for(let i=start;i<text.length;i++){
            const ch=text[i];
            if(inString){if(escape)escape=false;else if(ch==='\\')escape=true;else if(ch==='"')inString=false;continue}
            if(ch==='"'){inString=true;continue}
            if(ch==='{')depth++;
            if(ch==='}'&&--depth===0){
              try{return JSON.parse(text.slice(start,i+1))}catch{return null}
            }
          }
          return null;
        }
        const nativeRunData=getRunData(raw);
        const immutableSource=await readFile(join('/opt/procureflow-scenarios',id+'.json'),'utf8');
        const actualNames=new Set(JSON.parse(immutableSource).nodes.map(n=>n.name));
        const completedIds=nativeRunData?Object.keys(nativeRunData).filter(name=>actualNames.has(name)):[];
        resolve({scenario:id,engine:'n8n-cli-2.44.6',success,error:errorMessage,
          executedNodes:completedIds,
          logTail:success?undefined:raw.slice(-1400),
          bidSubmitted:false,immutableFixture:true});
      });
  });
}
createServer(async (req,res)=>{
  const path=new URL(req.url||'/', 'http://local').pathname;
  if(req.method==='GET'&&path==='/healthz')return send(res,200,{ok:true,engine:'n8n CLI',mode:'immutable-demo-only',busy});
  if(req.method==='GET'&&path==='/scenarios')return send(res,200,{scenarios:Array.from({length:10},(_,i)=>'S'+String(i+1).padStart(2,'0'))});
  const match=/^\/run\/(S(?:0[1-9]|10))$/.exec(path);
  if(req.method==='POST'&&match){
    if(req.headers.origin!==ORIGIN)return send(res,403,{error:'ORIGIN_REQUIRED'});
    if(busy)return send(res,429,{error:'ONE_NATIVE_EXECUTION_AT_A_TIME'});
    if(Date.now()-lastStarted<12000)return send(res,429,{error:'COOLDOWN_12_SECONDS'});
    // Reject payloads: the execution target and parameters are ALWAYS server-side immutable fixtures.
    if(Number(req.headers['content-length']||0)>0)return send(res,400,{error:'NO_CLIENT_WORKFLOW_INPUTS'});
    busy=true;lastStarted=Date.now();
    try{
      const outcome=await runN8n(match[1]);
      const body={...outcome,generatedAt:new Date().toISOString()};
      results.set(match[1],body);
      return send(res,outcome.success?200:502,body);
    }catch(e){return send(res,502,{error:'NATIVE_EXECUTION_FAILED',reason:String(e).slice(0,350)})}
    finally{busy=false}
  }
  return send(res,404,{error:'NOT_FOUND'});
}).listen(PORT,'0.0.0.0',()=>console.log('[procureflow native runner] listening',PORT));
