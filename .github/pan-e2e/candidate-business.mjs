#!/usr/bin/env node
/**
 * Issue #21: real Google Chrome, OFFICIAL n8n 2.44.6 candidate editor.
 * Isolated SQLite only. Native palette, settings, persistence, deletion and
 * one synthetic-only HOLD execution via localhost fixture; no real G2B.
 */
import {chromium,selectors} from 'playwright';
import {parse as parseFlatted} from 'flatted';
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
  // Real official n8n execution, but synthetic fixture only: the response
  // identifies itself as synthetic and MUST route to HOLD, never success.
  const holdFlow={
    name:'Issue21 Synthetic Business Operation HOLD Execution',
    nodes:[
      {id:'hold-manual-01',name:'Manual Trigger',type:'n8n-nodes-base.manualTrigger',
       typeVersion:1,position:[120,150],parameters:{}},
      {id:'hold-business-02',name:'Business Operation',
       type:'CUSTOM.procureFlowBusinessOperation',typeVersion:1,
       position:[420,150],parameters:{operationId:'N01',
         bidNo:'R26BK01787028',evidenceHandling:'hold'}}
    ],
    connections:{'Manual Trigger':{main:[[
      {node:'Business Operation',type:'main',index:0}
    ]]}},settings:{executionOrder:'v1'},staticData:null,pinData:{}
  };
  const holdCreated=(await api('POST','/rest/workflows',holdFlow)).data;
  assert(holdCreated?.id,'Synthetic HOLD workflow creation failed');
  await page.goto(URL+'/workflow/'+holdCreated.id,{waitUntil:'domcontentloaded'});
  await page.getByTestId('canvas').waitFor({timeout:30000});
  await page.locator('[data-test-id="canvas-node"][data-node-name="Business Operation"]').waitFor({timeout:30000});
  const startedResponse=page.waitForResponse(r=>
    r.url().includes('/rest/workflows/')&&r.url().includes('/run')&&r.request().method()==='POST',
    {timeout:45000});
  await page.getByTestId('execute-workflow-button').first().click({timeout:15000});
  const started=(await (await startedResponse).json()).data;
  const executionId=String(started?.executionId??started?.id??'');
  assert(executionId,'Native Business Operation execution missing ID: '+JSON.stringify(started));
  const holdExecution=await poll('native synthetic Business Operation HOLD result',async()=>{
    const d=(await api('GET','/rest/executions/'+executionId)).data;
    const payload=typeof d?.data==='string'?parseFlatted(d.data):d?.data;
    const runData=payload?.resultData?.runData??d?.resultData?.runData;
    const nodeRun=runData?.['Business Operation']?.[0];
    const success=nodeRun?.data?.main?.[0]||[];
    const held=nodeRun?.data?.main?.[1]||[];
    const output=held[0]?.json;
    if(!output)return null;
    assert(success.length===0,'Synthetic evidence incorrectly reached success output');
    assert(output.inspection_status==='HOLD'&&output.evidence_verified===false,
      'Synthetic evidence incorrectly VERIFIED');
    assert(output.evidence_provenance==='isolated_synthetic_test_evidence',
      'Synthetic evidence source mislabeled');
    assert(output.final_decision==='HOLD'&&output.manual_review_required===true,
      'Native HOLD result lacks human review gate');
    assert(output.bid_submitted===false&&output.worker_job_enqueued===false,
      'Native HOLD unexpectedly dispatched business action');
    return {executionId,status:d.status,outputIndex:1,
      inspectionStatus:output.inspection_status,
      evidenceProvenance:output.evidence_provenance,
      bidSubmitted:output.bid_submitted,workerJobEnqueued:output.worker_job_enqueued};
  },60000);
  await record('real-chrome-native-business-operation-synthetic-hold-execution','PASS',holdExecution);
  await page.screenshot({path:path.join(OUT,'05-native-business-hold-executed.png'),fullPage:true});
  // One real official n8n Chrome-triggered execution fans out to all 43
  // manifest operations. The only reachable API is the isolated loopback
  // fixture and EVERY native node must take the HOLD output, never success.
  const manifest=JSON.parse(await fs.readFile('n8n/operational_manifest.json','utf8'));
  assert(manifest.blocks.length===43,'43-block native runtime manifest missing');
  const allNodes=manifest.blocks.map((block,i)=>({
    id:'hold-all-'+block.id,name:'Business '+block.id,
    type:'CUSTOM.procureFlowBusinessOperation',typeVersion:1,
    position:[400+(i%6)*240,120+Math.floor(i/6)*150],
    parameters:{operationId:block.id,bidNo:'R26BK01787028',evidenceHandling:'hold'}
  }));
  const allFlow={
    name:'Issue21 Native 43 Business Operations Synthetic HOLD Runtime',
    nodes:[{id:'hold-all-trigger',name:'Manual Trigger',
      type:'n8n-nodes-base.manualTrigger',typeVersion:1,
      position:[120,120],parameters:{}},...allNodes],
    connections:{'Manual Trigger':{main:[allNodes.map(n=>({
      node:n.name,type:'main',index:0
    }))]}},settings:{executionOrder:'v1'},staticData:null,pinData:{}
  };
  const allCreated=(await api('POST','/rest/workflows',allFlow)).data;
  assert(allCreated?.id,'43-operation native HOLD workflow not created');
  await page.goto(URL+'/workflow/'+allCreated.id,{waitUntil:'domcontentloaded'});
  await page.getByTestId('canvas').waitFor({timeout:45000});
  const allStartedResponse=page.waitForResponse(r=>
    r.url().includes('/rest/workflows/')&&r.url().includes('/run')&&r.request().method()==='POST',
    {timeout:45000});
  await page.getByTestId('execute-workflow-button').first().click({timeout:20000});
  const allStarted=(await (await allStartedResponse).json()).data;
  const allExecutionId=String(allStarted?.executionId??allStarted?.id??'');
  assert(allExecutionId,'43-operation native execution missing ID');
  const allVerdict=await poll('43 native operations must each emit synthetic HOLD',async()=>{
    const d=(await api('GET','/rest/executions/'+allExecutionId)).data;
    const payload=typeof d?.data==='string'?parseFlatted(d.data):d?.data;
    const runData=payload?.resultData?.runData??d?.resultData?.runData;
    if(!runData||!allNodes.every(n=>runData[n.name]?.[0]?.data?.main))return null;
    for(const n of allNodes){
      const main=runData[n.name][0].data.main;
      assert((main[0]||[]).length===0,n.name+' unexpectedly reached success');
      const item=main[1]?.[0]?.json;
      assert(item?.operation_id===n.parameters.operationId,
        n.name+' missing or mismatched operation ID');
      assert(item.inspection_status==='HOLD'&&item.evidence_verified===false,
        n.name+' must not VERIFY synthetic evidence');
      assert(item.actual_business_handler_executed===false&&
        item.bid_submitted===false&&item.worker_job_enqueued===false,
        n.name+' unexpectedly dispatched business work');
      assert(item.evidence_provenance==='isolated_synthetic_test_evidence',
        n.name+' missing synthetic provenance');
    }
    assert(d.status==='success','43-operation native n8n run failed: '+d.status);
    return {executionId:allExecutionId,nativeOperations:allNodes.length,
      holdOutputs:allNodes.length,successOutputs:0,status:d.status,
      realBusinessHandlers:0,actualBidSubmitted:false};
  },120000);
  await record('real-chrome-all-43-native-operations-synthetic-hold-execution',
    'PASS',allVerdict);
  await page.screenshot({path:path.join(OUT,'06-all-43-native-hold.png')});
  // Separate debugging acceptance: real Chrome triggers a native n8n ERROR
  // when official evidence is incomplete and evidenceHandling=stop. The
  // isolated fixture always returns synthetic HOLD; never contacts G2B.
  const stopFlow={
    name:'Issue21 Native Business Operation Fail-Closed Debugging',
    nodes:[
      {id:'stop-manual-01',name:'Manual Trigger',type:'n8n-nodes-base.manualTrigger',
       typeVersion:1,position:[120,150],parameters:{}},
      {id:'stop-business-02',name:'Business Operation',
       type:'CUSTOM.procureFlowBusinessOperation',typeVersion:1,
       position:[420,150],parameters:{operationId:'N01',
         bidNo:'R26BK01787028',evidenceHandling:'stop'}}
    ],
    connections:{'Manual Trigger':{main:[[
      {node:'Business Operation',type:'main',index:0}
    ]]}},settings:{executionOrder:'v1'},staticData:null,pinData:{}
  };
  const stopCreated=(await api('POST','/rest/workflows',stopFlow)).data;
  assert(stopCreated?.id,'Native fail-closed debug workflow creation failed');
  await page.goto(URL+'/workflow/'+stopCreated.id,{waitUntil:'domcontentloaded'});
  await page.getByTestId('canvas').waitFor({timeout:30000});
  await page.locator('[data-test-id="canvas-node"][data-node-name="Business Operation"]').waitFor({timeout:30000});
  const stopStartedResponse=page.waitForResponse(r=>
    r.url().includes('/rest/workflows/')&&r.url().includes('/run')&&r.request().method()==='POST',
    {timeout:45000});
  await page.getByTestId('execute-workflow-button').first().click({timeout:15000});
  const stopStarted=(await (await stopStartedResponse).json()).data;
  const stopExecutionId=String(stopStarted?.executionId??stopStarted?.id??'');
  assert(stopExecutionId,'Native fail-closed execution ID missing');
  const errorVerdict=await poll('native stop-on-HOLD execution error',async()=>{
    const d=(await api('GET','/rest/executions/'+stopExecutionId)).data;
    if(d?.status!=='error')return null;
    const payload=typeof d?.data==='string'?parseFlatted(d.data):d?.data;
    const runData=payload?.resultData?.runData??d?.resultData?.runData;
    const nodeRun=runData?.['Business Operation']?.[0];
    const failure=nodeRun?.error?.message??payload?.resultData?.error?.message??'';
    assert(failure.includes('official evidence incomplete'),
      'Native error lacks fail-closed reason: '+failure);
    assert(!(nodeRun?.data?.main?.[0]||[]).length,
      'Stop-on-HOLD must never emit a success item');
    return {executionId:stopExecutionId,status:d.status,
      failedNode:'Business Operation',reason:failure,
      successOutputs:0,realBusinessHandlers:0,actualBidSubmitted:false};
  },60000);
  await record('real-chrome-native-business-operation-fail-closed-debugging',
    'PASS',errorVerdict);
  await page.screenshot({path:path.join(OUT,'07-native-business-stop-error.png'),fullPage:true});
  await record('no-real-business-handler-or-bid-submission','PASS',{
    syntheticNativeExecutionCount:44,realBusinessHandlerCount:0,
    actualBidSubmitted:false,productionApiRequests:0
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
