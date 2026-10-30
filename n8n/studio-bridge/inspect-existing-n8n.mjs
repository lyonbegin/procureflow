#!/usr/bin/env node
/**
 * Read-only n8n inventory bridge for the ALREADY-EXISTING operational instance.
 * - NEVER creates an owner, executes, imports, edits, activates or publishes.
 * - NO n8n API credentials in browser, logs, source control, or output.
 * - If owner is unclaimed or API key is absent, reports BLOCKED and does not
 *   attempt a substitute n8n instance / database initialization.
 * - Operations and scenarios from PF_OPERATIONS_DIR/PF_SCENARIOS_DIR are
 *   compared to official n8n API workflow names; diff never writes to n8n.
 */
import {readFile} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

export const candidatePaths=Object.freeze([
 ...Array.from({length:16},(_,i)=>['operations','PF'+String(i).padStart(2,'0')+'.json']),
 ...Array.from({length:10},(_,i)=>['scenarios','S'+String(i+1).padStart(2,'0')+'.json'])
]);
export const blockingVerdicts=Object.freeze({
 NO_API_KEY:'BLOCKED_MISSING_EXISTING_N8N_API_KEY',
 OWNER_SETUP:'BLOCKED_EXISTING_N8N_OWNER_SETUP',
 API_UNAUTHORIZED:'BLOCKED_EXISTING_N8N_API_UNAUTHORIZED',
 API_UNAVAILABLE:'BLOCKED_EXISTING_N8N_API_UNAVAILABLE'
});
async function readJson(endpoint,headers={},transport=fetch){
 const res=await transport(endpoint,{method:'GET',headers,redirect:'error',
   signal:AbortSignal.timeout(15000)});
 if(!res.ok){const err=new Error('n8n GET returned HTTP '+res.status);
   err.status=res.status;throw err;}
 return res.json();
}
export async function inspectExistingN8n({baseUrl,apiKey,operationsDir,scenariosDir,transport=fetch}){
 if(!baseUrl)throw Error('N8N_BASE_URL is required (the existing service address)');
 const root=baseUrl.replace(/\/+$/,'');
 // Public read of settings is informational only. Missing/odd payload does
 // not justify initializing an owner or bypassing auth.
 let ownerSetupRequired=null,settingsStatus=null;
 try{
  const settings=await readJson(root+'/rest/settings',{},transport);
  settingsStatus=200;
  ownerSetupRequired=settings?.data?.userManagement?.showSetupOnFirstLoad===true;
 }catch(e){settingsStatus=e.status??null;}
 if(ownerSetupRequired===true)
  return {ready:false,verdict:blockingVerdicts.OWNER_SETUP,settingsStatus,
    ownerSetupRequired,apiWrites:0,ownerCreated:false,workflowExecuted:false};
 if(!apiKey)
  return {ready:false,verdict:blockingVerdicts.NO_API_KEY,settingsStatus,
    ownerSetupRequired,apiWrites:0,ownerCreated:false,workflowExecuted:false};
 const headers={'X-N8N-API-KEY':apiKey,'Accept':'application/json'};
 try{
  const installed=[],cursors=new Set();
  let cursor='';
  do{
   const url=new URL(root+'/api/v1/workflows');
   url.searchParams.set('limit','250');
   if(cursor)url.searchParams.set('cursor',cursor);
   const page=await readJson(url.toString(),headers,transport);
   if(!Array.isArray(page?.data))throw Error('n8n API unexpected list schema');
   installed.push(...page.data);
   const next=typeof page.nextCursor==='string'?page.nextCursor:'';
   if(next&&cursors.has(next))throw Error('n8n pagination cycle');
   if(next)cursors.add(next);
   cursor=next;
   if(cursors.size>200)throw Error('n8n pagination exceeded safe read limit');
  }while(cursor);
  const candidates=[];
  for(const [scope,file] of candidatePaths){
   const directory=scope==='operations'?operationsDir:scenariosDir;
   if(!directory)continue;
   const flow=JSON.parse(await readFile(join(directory,file),'utf8'));
   candidates.push({id:scope+'/'+file,name:flow.name,nodes:flow.nodes?.length||0});
  }
  const byName=new Map();
  for(const w of installed){const list=byName.get(w.name)||[];list.push(w);byName.set(w.name,list);}
  const matched=candidates.map(x=>({...x,
    status:(byName.get(x.name)||[]).length===0?'NOT_FOUND':
      (byName.get(x.name)||[]).length===1?'NAME_MATCH':'AMBIGUOUS_DUPLICATE_NAME',
    existingIds:(byName.get(x.name)||[]).map(z=>z.id),
    active:(byName.get(x.name)||[]).map(z=>!!z.active)}));
  return {ready:true,verdict:'READ_ONLY_INVENTORY_OK',
    ownerSetupRequired,installedWorkflows:installed.length,candidates:matched,
    missing:matched.filter(w=>w.status!=='NAME_MATCH').length,
    apiWrites:0,ownerCreated:false,workflowExecuted:false};
 }catch(error){
  return {ready:false,
    verdict:error.status===401||error.status===403?blockingVerdicts.API_UNAUTHORIZED:blockingVerdicts.API_UNAVAILABLE,
    ownerSetupRequired,apiStatus:error.status??null,apiWrites:0,ownerCreated:false,workflowExecuted:false};
 }
}
async function main(){
 const result=await inspectExistingN8n({
  baseUrl:process.env.N8N_BASE_URL,
  apiKey:process.env.N8N_API_KEY,
  operationsDir:process.env.PF_OPERATIONS_DIR,
  scenariosDir:process.env.PF_SCENARIOS_DIR
 });
 process.stdout.write(JSON.stringify(result,null,2)+'\n');
 if(!result.ready)process.exitCode=2;
}
// A library import must NEVER inspect a real n8n host.
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))
 main().catch(e=>{process.stderr.write('READ_ONLY_N8N_INVENTORY_ERROR '+e.message+'\n');process.exitCode=2});
