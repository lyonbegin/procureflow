import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {candidatePaths} from '../n8n/studio-bridge/inspect-existing-n8n.mjs';
import {installCandidates,sanitize} from '../n8n/studio-bridge/import-inactive-existing-n8n.mjs';
const root=await mkdtemp(join(tmpdir(),'n8n-inactive-import-'));
const operationsDir=join(root,'operations'),scenariosDir=join(root,'scenarios');
await mkdir(operationsDir);await mkdir(scenariosDir);
const baseUrl='https://n8n.example.invalid';
const flow=(name)=>({name,nodes:[{id:'node-1',name:'Manual',type:'n8n-nodes-base.manualTrigger',typeVersion:1,position:[0,0],parameters:{}}],connections:{}});
for(const [scope,file] of candidatePaths)await writeFile(join(root,scope,file),JSON.stringify(flow(scope+'/'+file)));
let requests=[],created=0;
const transport=async(url,opts)=>{
 requests.push({url,method:opts.method,body:opts.body});
 if(url.endsWith('/rest/settings'))return {ok:true,json:async()=>({data:{userManagement:{showSetupOnFirstLoad:false}}})};
 if(opts.method==='POST'){created++;return {ok:true,json:async()=>({id:'new-'+created})};}
 return {ok:true,json:async()=>({data:[],nextCursor:null})};
};
try{
 assert.throws(()=>sanitize({...flow('x'),nodes:[{type:'CUSTOM.procureFlowBusinessOperation',name:'gate'}]}),/Uninstalled CUSTOM/);
 const args={baseUrl,apiKey:'test-key',operationsDir,scenariosDir,transport};
 const plan=await installCandidates(args);
 assert.equal(plan.mode,'DRY_RUN');assert.equal(plan.total,26);
 assert.equal(created,0);assert(requests.every(x=>x.method==='GET'));
 requests=[];
 const applied=await installCandidates({...args,apply:true});
 assert.equal(applied.created,26);assert.equal(created,26);
 assert.equal(applied.activeChanges,0);assert.equal(applied.executions,0);
 assert(requests.filter(x=>x.method==='POST').every(x=>JSON.parse(x.body).active===undefined));
 // No owner endpoint is necessary for a configured service-to-service API connection.
 assert(requests.every(x=>!x.url.includes('/rest/owner')&&!x.url.includes('/rest/settings')));
 console.log('EXISTING_N8N_INACTIVE_IMPORT_TEST_PASS: dryrun 0 writes, explicit 26 inactive creates, owner guard, no run');
}finally{await rm(root,{recursive:true,force:true});}
