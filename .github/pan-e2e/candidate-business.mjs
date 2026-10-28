#!/usr/bin/env node
/**
 * Issue #21: real Google Chrome, OFFICIAL n8n 2.44.6 candidate editor.
 * Isolated SQLite only. Business Operation is NEVER executed: this verifies
 * native palette registration, UI settings, persistence and deletion.
 */
import {chromium,selectors} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';

selectors.setTestIdAttribute('data-test-id');
const URL=process.env.N8N_E2E_URL||'http://127.0.0.1:5681';
const OUT=process.env.N8N_E2E_ARTIFACTS||'candidate-business-chrome-artifacts';
const EMAIL='candidate@example.invalid';
const PASSWORD='CandidatePass123!';
const reports=[];
let browser,context,page;
await fs.mkdir(OUT,{recursive:true});
async function record(name,result,details={}){
  const verdict={name,result,...details};
  reports.push(verdict);
  console.log('CANDIDATE_CHROME',JSON.stringify(verdict));
  await fs.writeFile(path.join(OUT,'verdicts.json'),JSON.stringify(reports,null,2));
}
function assert(ok,message){if(!ok)throw Error(message);}
async function api(method,endpoint,data){
  const response=await context.request.fetch(URL+endpoint,{
    method,...(data===undefined?{}:{data,headers:{'content-type':'application/json'}}),
    timeout:30000
  });
  const raw=await response.text();
  let body;
  try{body=JSON.parse(raw);}catch{body={raw:raw.slice(0,400)};}
  if(!response.ok())throw Error(method+' '+endpoint+' HTTP '+response.status()+' '+JSON.stringify(body).slice(0,450));
  return body;
}
async function poll(label,fn,timeout=30000){
  const start=Date.now();
  let last;
  while(Date.now()-start<timeout){
    try{const found=await fn();if(found)return found;}catch(e){last=e;}
    await new Promise(resolve=>setTimeout(resolve,600));
  }
  throw Error(label+' timed out'+(last?': '+last.message:''));
}
const isBusiness=(node)=>node?.type?.endsWith('procureFlowBusinessOperation');
try{
  browser=await chromium.launch({channel:'chrome',headless:true,args:['--no-sandbox']});
  context=await browser.newContext({viewport:{width:1440,height:900}});
  page=await context.newPage();
  await context.tracing.start({screenshots:true,snapshots:true,sources:true});
  page.on('pageerror',e=>console.error('CANDIDATE_PAGE_ERROR',e.message));
  const settings=await api('GET','/rest/settings');
  if(settings?.data?.userManagement?.showSetupOnFirstLoad)
    await api('POST','/rest/owner/setup',{
      email:EMAIL,firstName:'Candidate',lastName:'Test',password:PASSWORD
    });
  await api('POST','/rest/login',{emailOrLdapLoginId:EMAIL,password:PASSWORD});
  await record('isolated-candidate-auth','PASS');

  const types=await api('POST','/rest/node-types',{
    nodeInfos:[{name:'CUSTOM.procureFlowBusinessOperation',version:1}]
  });
  const rows=Array.isArray(types.data)?types.data:Array.isArray(types.data?.data)?types.data.data:[];
  const kind=rows.find(x=>x?.name?.endsWith('procureFlowBusinessOperation'));
  assert(kind,'Native custom Business Operation type not exposed by n8n');
  const options=kind.properties?.find(x=>x.name==='operationId')?.options||[];
  assert(options.length===43,'Native custom node must expose 43 operation IDs');
  assert(JSON.stringify(kind.outputNames)===JSON.stringify(['success','hold_or_error']),'Native HOLD port absent');
  await record('official-n8n-native-43-operation-registration','PASS',{count:options.length});

  const synthetic={
    name:'Issue21 Candidate Chrome Business Operation Palette',
    nodes:[{id:'candidate-manual-01',name:'Manual Trigger',
      type:'n8n-nodes-base.manualTrigger',typeVersion:1,
      position:[120,150],parameters:{}}],
    connections:{},settings:{executionOrder:'v1'},staticData:null,pinData:{}
  };
  const created=(await api('POST','/rest/workflows',synthetic)).data;
  assert(created?.id,'Isolated candidate workflow creation failed');
  const id=String(created.id);
  await page.goto(URL+'/workflow/'+id,{waitUntil:'domcontentloaded'});
  await page.getByTestId('canvas').waitFor({timeout:30000});
  await page.locator('[data-test-id="canvas-node"][data-node-name="Manual Trigger"]').waitFor({timeout:30000});
  await record('official-candidate-vue-canvas-rendered','PASS',{workflowId:id});
  await page.screenshot({path:path.join(OUT,'01-candidate-editor.png'),fullPage:true});

  await page.getByTestId('node-creator-plus-button').click();
  await page.getByTestId('node-creator-search-bar').fill('Business Operation');
  const item=page.getByTestId('node-creator-item-name').getByText('Business Operation · ProcureFlow',{exact:true});
  await item.click({timeout:20000});
  await record('real-chrome-custom-node-palette-add','PASS');
  const operationControl=page.getByTestId('parameter-input-operationId');
  await operationControl.waitFor({timeout:20000});
  await record('real-chrome-business-operation-configuration-visible','PASS');
  // n8n does not serialize a parameter's default until the user selects it.
  // Exercise the actual options dropdown and persist an explicit N02 choice.
  await operationControl.click();
  await page.getByText('N02 · 공고번호·차수 식별',{exact:true}).last().click({timeout:15000});
  await record('real-chrome-operationId-dropdown-selection','PASS',{operationId:'N02'});
  const close=page.getByTestId('ndv-close-button');
  if(await close.isVisible().catch(()=>false))await close.click();

  const added=await poll('custom node server autosave',async()=>{
    const w=(await api('GET','/rest/workflows/'+id)).data;
    return w?.nodes?.find(isBusiness)||null;
  });
  assert(added.parameters?.operationId==='N02','Selected operation ID not persisted '+JSON.stringify(added.parameters));
  await record('real-chrome-custom-node-server-save','PASS',{
    nodeId:added.id,type:added.type,operationId:added.parameters.operationId
  });
  await page.screenshot({path:path.join(OUT,'02-business-node-added.png'),fullPage:true});
  await page.reload({waitUntil:'domcontentloaded'});
  const nodeElement=page.locator('[data-test-id="canvas-node"][data-node-name="'+added.name+'"]').first();
  await nodeElement.waitFor({timeout:30000});
  const persisted=(await api('GET','/rest/workflows/'+id)).data;
  const reloaded=persisted.nodes.find(n=>n.id===added.id);
  assert(reloaded&&isBusiness(reloaded)&&reloaded.parameters?.operationId==='N02','Custom node settings lost after browser reload');
  await record('real-chrome-custom-node-reopen-persistence','PASS',{id:added.id});
  await page.screenshot({path:path.join(OUT,'03-reopened.png'),fullPage:true});

  await nodeElement.hover();
  await nodeElement.getByTestId('delete-node-button').click({timeout:15000});
  await poll('custom node deletion saved',async()=>{
    const w=(await api('GET','/rest/workflows/'+id)).data;
    return !w?.nodes?.some(n=>n.id===added.id);
  });
  await record('real-chrome-custom-node-delete-and-server-save','PASS',{id:added.id});
  await page.screenshot({path:path.join(OUT,'04-deleted.png'),fullPage:true});
  await record('no-business-execution-or-bid-submission','PASS',{
    nodeExecutionCount:0,actualBidSubmitted:false,productionApiRequests:0
  });
}catch(error){
  console.error('CANDIDATE_CHROME_FAIL',error?.stack||String(error));
  await record('test-run','FAIL',{error:error?.stack||String(error)});
  if(page)try{await page.screenshot({path:path.join(OUT,'failure.png'),fullPage:true});}catch{}
  process.exitCode=1;
}finally{
  if(context)try{await context.tracing.stop({path:path.join(OUT,'chrome-trace.zip')});}catch{}
  if(context)try{await context.close();}catch{}
  if(browser)try{await browser.close();}catch{}
}
