import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {inspectExistingN8n,blockingVerdicts,candidatePaths} from '../n8n/studio-bridge/inspect-existing-n8n.mjs';
const root=await mkdtemp(join(tmpdir(),'procureflow-existing-n8n-'));
const ops=join(root,'operations'),scenes=join(root,'scenarios');
await mkdir(ops);await mkdir(scenes);
for(const [scope,file] of candidatePaths){
 const name=file==='PF00.json'?'[운영 PF00] 테스트 후보':
    file==='S01.json'?'[테스트 S01] 가상 후보':'[그 외 '+file+']';
 const folder=scope==='operations'?ops:scenes;
 await writeFile(join(folder,file),JSON.stringify({name,nodes:[{id:'1'}]}));
}
try{
 const urls=[],makeTransport=(owner,authorized)=>async (url,req)=>{
   urls.push({url,method:req.method,headers:req.headers});
   assert.equal(req.method,'GET','n8n inventory bridge must NEVER write');
   if(url.endsWith('/rest/settings'))
      return {ok:true,json:async()=>({data:{userManagement:{showSetupOnFirstLoad:owner}}})};
   assert(req.headers?.['X-N8N-API-KEY'],'API key must only be sent to n8n API GET');
   if(!authorized)return {ok:false,status:401};
   return {ok:true,json:async()=>({data:[{id:'existing-PF00',name:'[운영 PF00] 테스트 후보',active:false}],nextCursor:null})};
 };
 const blockedOwner=await inspectExistingN8n({
   baseUrl:'https://existing-n8n.invalid',apiKey:'test-only-key',
   operationsDir:ops,scenariosDir:scenes,transport:makeTransport(true,true)
 });
 assert.equal(blockedOwner.verdict,blockingVerdicts.OWNER_SETUP);
 assert.equal(urls.length,1,'Owner-unclaimed must not request inventory');
 const noKey=await inspectExistingN8n({
   baseUrl:'https://existing-n8n.invalid',operationsDir:ops,scenariosDir:scenes,transport:makeTransport(false,true)
 });
 assert.equal(noKey.verdict,blockingVerdicts.NO_API_KEY);
 assert.equal(urls.length,2,'Missing API key must not query workflows');
 const noAuth=await inspectExistingN8n({
   baseUrl:'https://existing-n8n.invalid',apiKey:'test-only-key',operationsDir:ops,scenariosDir:scenes,transport:makeTransport(false,false)
 });
 assert.equal(noAuth.verdict,blockingVerdicts.API_UNAUTHORIZED);
 const report=await inspectExistingN8n({
   baseUrl:'https://existing-n8n.invalid',apiKey:'test-only-key',operationsDir:ops,scenariosDir:scenes,transport:makeTransport(false,true)
 });
 assert.equal(report.ready,true);
 assert.equal(report.installedWorkflows,1);
 assert.equal(report.candidates.length,26);
 assert.equal(report.candidates[0].status,'NAME_MATCH');
 assert.equal(report.candidates[1].status,'NOT_FOUND');
 assert.equal(report.missing,25);
 assert.equal(report.apiWrites,0);
 assert.equal(report.workflowExecuted,false);
 assert.equal(report.ownerCreated,false);
 assert(!JSON.stringify(report).includes('test-only-key'),'Never report n8n API key');
 assert(urls.every(x=>x.method==='GET'));
 console.log('EXISTING_N8N_STUDIO_READ_ONLY_BRIDGE_MOCK_PASS',JSON.stringify({
   ownerUnclaimedBlocked:true,missingKeyBlocked:true,unauthorizedBlocked:true,
   inventoryDiffReadOnly:true,apiWrites:0,ownerWrites:0,executions:0
 }));
}finally{await rm(root,{recursive:true,force:true});}
