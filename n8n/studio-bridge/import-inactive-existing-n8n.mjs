#!/usr/bin/env node
// Explicit, safety-gated importer for the EXISTING official n8n engine only.
// No owner setup, no DB reset, no activation, no workflow execution.
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {candidatePaths} from './inspect-existing-n8n.mjs';
const liveFlags=new Set(process.argv.slice(2));
export function sanitize(flow){
 if(!flow||!Array.isArray(flow.nodes)||!flow.connections)throw Error('Invalid workflow');
 for(const n of flow.nodes){
  if(n.type==='CUSTOM.procureFlowBusinessOperation')throw Error('Uninstalled CUSTOM node: '+n.name);
  if(n.type?.includes('executeCommand'))throw Error('Shell execution node prohibited');
 }
 // n8n public API accepts these workflow create/update contract fields.
 return {name:flow.name,nodes:flow.nodes,connections:flow.connections,
  settings:flow.settings||{},staticData:null};
}
export async function installCandidates({baseUrl,apiKey,operationsDir,scenariosDir,apply=false,transport=fetch}){
 if(!baseUrl||!apiKey)throw Error('Existing N8N_BASE_URL and N8N_API_KEY required');
 if(!/^https:\/\//.test(baseUrl)&&!/^http:\/\/127\.0\.0\.1(:\d+)?$/.test(baseUrl))throw Error('HTTPS existing n8n required');
 const root=baseUrl.replace(/\/+$/,'');
 const request=async(url,options={})=>{
  const response=await transport(root+url,{
   method:options.method||'GET',headers:{'Accept':'application/json',
    'X-N8N-API-KEY':apiKey,...(options.body?{'Content-Type':'application/json'}:{})},
   ...(options.body?{body:JSON.stringify(options.body)}:{}),redirect:'error',
   signal:AbortSignal.timeout(15000)
  });
  if(!response.ok)throw Error('Official n8n API HTTP '+response.status);
  return response.json();
 };
 const settingsResponse=await transport(root+'/rest/settings',{method:'GET',redirect:'error',signal:AbortSignal.timeout(15000)});
 if(!settingsResponse.ok)throw Error('Existing owner status unreadable; stop');
 const status=await settingsResponse.json();
 if(status?.data?.userManagement?.showSetupOnFirstLoad!==false)
  throw Error('Existing owner not confirmed configured; no writes');
 const installed=[],seen=new Set();let cursor='';
 do{
  const suffix=cursor?'&cursor='+encodeURIComponent(cursor):'';
  const page=await request('/api/v1/workflows?limit=250'+suffix);
  if(!Array.isArray(page.data))throw Error('Invalid workflow inventory');
  installed.push(...page.data);
  cursor=page.nextCursor||'';
  if(cursor&&seen.has(cursor))throw Error('Pagination cycle');
  if(cursor)seen.add(cursor);
 }while(cursor);
 const byName=new Map();
 for(const flow of installed){byName.set(flow.name,[...(byName.get(flow.name)||[]),flow]);}
 const plans=[];
 for(const [folder,file] of candidatePaths){
  const dir=folder==='operations'?operationsDir:scenariosDir;
  const raw=JSON.parse(await readFile(path.join(dir,file),'utf8'));
  // Generated PF graphs may carry CUSTOM gates which official engine cannot execute.
  const workflow=sanitize(raw);
  const match=byName.get(workflow.name)||[];
  if(match.length>1)throw Error('Ambiguous existing workflow name: '+workflow.name);
  plans.push({path:folder+'/'+file,name:workflow.name,
   action:match.length?'ALREADY_EXISTS':'CREATE_INACTIVE',workflow});
 }
 // By design: never overwrite existing workflows; never activate, publish or execute.
 if(apply){
  for(const plan of plans.filter(p=>p.action==='CREATE_INACTIVE')){
   const created=await request('/api/v1/workflows',{method:'POST',body:plan.workflow});
   if(!created?.id)throw Error('n8n did not return new workflow id');
   plan.createdId=created.id;
  }
 }
 return {mode:apply?'APPLIED_INACTIVE':'DRY_RUN',total:plans.length,
  existing:plans.filter(p=>p.action==='ALREADY_EXISTS').length,
  create:plans.filter(p=>p.action==='CREATE_INACTIVE').length,
  created:plans.filter(p=>p.createdId).length,activeChanges:0,
  executions:0,ownerChanges:0,
  plans:plans.map(({path,name,action,createdId})=>({path,name,action,createdId}))};
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const apply=liveFlags.has('--apply');
 if(apply&&process.env.PF_ALLOW_INACTIVE_IMPORT!=='YES')
  throw Error('Explicit PF_ALLOW_INACTIVE_IMPORT=YES required for --apply');
 installCandidates({baseUrl:process.env.N8N_BASE_URL,apiKey:process.env.N8N_API_KEY,
  operationsDir:process.env.PF_OPERATIONS_DIR,scenariosDir:process.env.PF_SCENARIOS_DIR,apply})
 .then(x=>console.log(JSON.stringify(x,null,2)))
 .catch(e=>{console.error('N8N_IMPORT_BLOCKED '+e.message);process.exitCode=2});
}
