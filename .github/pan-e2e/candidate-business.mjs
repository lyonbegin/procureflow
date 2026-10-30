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
import {assertIsolatedN8nUrl} from './scenario-safety.mjs';
import {createInspectionEnvelopeSchemas} from '../../n8n/source-build/inspection-envelope-schemas.mjs';

selectors.setTestIdAttribute('data-test-id');
// Fail closed BEFORE Chrome launch or owner/workflow writes: no production targets.
const URL=assertIsolatedN8nUrl(process.env.N8N_E2E_URL||'http://127.0.0.1:5681');
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
    timeout:30000,
    maxRedirects:0 // Playwright API requests bypass page.route()
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
  context=await browser.newContext({viewport:{width:1440,height:900},serviceWorkers:'block'});
  // The editor may fetch remote resources: isolate browser network too.
  await context.route('**/*',async route=>{
    if(new globalThis.URL(route.request().url()).origin!==URL)return route.abort();
    return route.continue();
  });
  // HTTP routing does not intercept WebSockets. Allow only the exact
  // disposable n8n origin; never open a cross-origin WS handshake.
  await context.routeWebSocket('**/*',async socket=>{
    const target=new globalThis.URL(socket.url());
    const allowed=new globalThis.URL(URL);
    if(target.protocol!=='ws:'||target.host!==allowed.host||
       target.username||target.password){await socket.close();return;}
    socket.connectToServer();
  });
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
  assert(kind.outputs?.length===2,'Custom node must expose two physical outputs');
  await record('official-n8n-native-43-operation-registration','PASS',{count:options.length});

  const synthetic={
    name:'Issue21 Candidate Chrome Business Operation Palette',
    nodes:[
      {id:'candidate-manual-01',name:'Manual Trigger',
       type:'n8n-nodes-base.manualTrigger',typeVersion:1,
       position:[120,530],parameters:{}},
      {id:'candidate-success-sink',name:'Accepted Sink',
       type:'n8n-nodes-base.code',typeVersion:2,
       position:[650,70],parameters:{mode:'runOnceForAllItems',
         jsCode:'return $input.all();'}},
      {id:'candidate-hold-sink',name:'Hold Sink',
       type:'n8n-nodes-base.code',typeVersion:2,
       position:[650,360],parameters:{mode:'runOnceForAllItems',
         jsCode:'return $input.all();'}}
    ],
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

  // Negative official Chrome acceptance: these 35 shared catalog recipes
  // have NO verified executable adapter in ProcureFlow. They must not be
  // advertised as first-class custom nodes in the native n8n palette.
  // This does not claim that unrelated n8n native nodes are disabled.
  const unsupportedSharedKinds=[
    "Retry / Timeout",
    "Error Handler / HALT",
    "Join / Quorum",
    "Human Approval",
    "File / Document",
    "Schema Validator",
    "Evidence / Audit",
    "Worker / Queue",
    "Resource / Lock",
    "Test / Mock / Assert",
    "Parallel Fork",
    "Event Publish",
    "Event Subscribe / Wait",
    "State Machine",
    "Compensation / Rollback",
    "Checkpoint / Resume",
    "Idempotency",
    "Deduplication",
    "Rate Limit",
    "Circuit Breaker",
    "Dead Letter Queue",
    "Lease / Fencing",
    "Data Mapper",
    "Split / Aggregate",
    "JSON Diff / Compare",
    "Completeness Gate",
    "Hash / Integrity",
    "Source Provenance",
    "Human Input / Form",
    "Permission Gate",
    "Notification / Alert",
    "Metrics / Counter",
    "Execution Probe",
    "Replay",
    "Fault Injection"
  ];
  await page.getByTestId('node-creator-plus-button').click();
  const paletteSearch=page.getByTestId('node-creator-search-bar');
  for(const unsupportedName of unsupportedSharedKinds){
    await paletteSearch.fill(unsupportedName);
    await page.waitForTimeout(300);
    const exact=page.getByTestId('node-creator-item-name').getByText(
      unsupportedName,{exact:true});
    assert(await exact.count()===0,
      'Unverified shared kind unexpectedly advertised in official palette: '+unsupportedName);
  }
  await record('real-chrome-35-unsupported-shared-kinds-not-advertised','PASS',{
    checked:unsupportedSharedKinds.length,
    limitation:'not a runnable mapping or a test of unrelated native n8n nodes'
  });
  await page.screenshot({path:path.join(OUT,'01b-unsupported-shared-kinds.png'),fullPage:true});
  await paletteSearch.fill('Business Operation');
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
  // Also exercise the real custom-node evidence policy selector; a default
  // shown in the editor is not proof that n8n persisted the parameter.
  const evidenceControl=page.getByTestId('parameter-input-evidenceHandling');
  await evidenceControl.click();
  await page.getByText('Return HOLD status, never mark complete',{exact:true}).last().click({timeout:15000});
  await record('real-chrome-evidence-handling-dropdown-selection','PASS',{evidenceHandling:'hold'});
  const close=page.getByTestId('ndv-close-button');
  if(await close.isVisible().catch(()=>false))await close.click();

  const added=await poll('custom node server autosave',async()=>{
    const w=(await api('GET','/rest/workflows/'+id)).data;
    return w?.nodes?.find(isBusiness)||null;
  });
  assert(added.parameters?.operationId==='N02','Selected operation ID not persisted '+JSON.stringify(added.parameters));
  assert(added.parameters?.evidenceHandling==='hold','Selected HOLD policy not persisted '+JSON.stringify(added.parameters));
  await record('real-chrome-custom-node-server-save','PASS',{
    nodeId:added.id,type:added.type,operationId:added.parameters.operationId
  });
  await page.screenshot({path:path.join(OUT,'02-business-node-added.png'),fullPage:true});
  await page.reload({waitUntil:'domcontentloaded'});
  const nodeElement=page.locator('[data-test-id="canvas-node"][data-node-name="'+added.name+'"]').first();
  await nodeElement.waitFor({timeout:30000});
  const persisted=(await api('GET','/rest/workflows/'+id)).data;
  const reloaded=persisted.nodes.find(n=>n.id===added.id);
  assert(reloaded&&isBusiness(reloaded)&&reloaded.parameters?.operationId==='N02'&&
    reloaded.parameters?.evidenceHandling==='hold','Custom node settings lost after browser reload');
  await record('real-chrome-custom-node-reopen-persistence','PASS',{id:added.id});
  // A workflow may render nodes while the native editor is still hydrating
  // or in view-only mode. Capture permissions and actual Chrome hit testing
  // before interpreting a failed drag as a node-movement implementation bug.
  const editState=await page.evaluate(()=>{
    const body=document.body.innerText;
    const controls=[...document.querySelectorAll('[data-test-id]')]
      .map(e=>e.getAttribute('data-test-id'))
      .filter(x=>/creator|zoom|edit|readonly|read-only/i.test(x||''));
    const node=document.querySelector('[data-test-id="canvas-node"][data-node-name="Business Operation"]');
    const rect=node?.getBoundingClientRect();
    const center=rect?{x:rect.x+rect.width/2,y:rect.y+rect.height/2}:null;
    const hit=center?document.elementFromPoint(center.x,center.y):null;
    return {readOnlyText:/read.only|view.only|no edit permission/i.test(body),
      readOnlyExcerpt:body.match(/.{0,65}(?:read.only|view.only|no edit permission).{0,65}/i)?.[0]||null,
      controls:[...new Set(controls)].slice(0,45),nodeRect:rect?{
        x:rect.x,y:rect.y,width:rect.width,height:rect.height}:null,
      centerHitNode:hit?.closest('[data-test-id="canvas-node"]')?.getAttribute('data-node-name')||null,
      centerHitTag:hit?.tagName||null};
  });
  const editWorkflow=(await api('GET','/rest/workflows/'+id)).data;
  await record('native-custom-node-post-reload-editability-diagnostic','OBSERVED',{
    workflowScopes:editWorkflow.scopes??null,
    plusVisible:await page.getByTestId('node-creator-plus-button').isVisible().catch(()=>false),
    editState
  });
  // The ProcureFlow custom node itself must support the same actual Chrome
  // drag -> n8n server autosave -> browser reload contract as native nodes.
  const originalPosition=[...reloaded.position];
  // n8n node children can carry Vue Flow's .nodrag class. A pointer hit
  // inside the node is NOT proof that the hit surface starts node dragging.
  // Discover actual draggable Chrome hit targets, reject no-drag/interactive
  // children, and use ONLY real mouse gestures. Do not REST/DOM-patch coords.
  await nodeElement.scrollIntoViewIfNeeded();
  await page.waitForTimeout(600);
  let movedPosition=null;
  const dragAttempts=[];
  const targets=[[.32,.14],[.50,.14],[.68,.14],[.18,.30],[.42,.28],
    [.70,.28],[.16,.50],[.50,.55],[.80,.55],[.18,.78],[.50,.80],[.80,.80]];
  for(const [fx,fy] of targets){
    const box=await nodeElement.boundingBox();
    assert(box,'Custom node is not visible for real Chrome drag');
    const x=box.x+box.width*fx,y=box.y+box.height*fy;
    const hit=await page.evaluate(({x,y})=>{
      const el=document.elementFromPoint(x,y);
      const classes=[];
      for(let p=el,i=0;p&&i<5;p=p.parentElement,i++)
        classes.push(String(p.className?.baseVal||p.className||'').slice(0,120));
      return {tag:el?.tagName||null,testId:el?.getAttribute('data-test-id')||null,
        node:el?.closest('[data-test-id="canvas-node"]')?.getAttribute('data-node-name')||null,
        noDrag:!!el?.closest('.nodrag,.nowheel,[data-no-drag],input,textarea,button,[role="button"]'),
        handle:!!el?.closest('.vue-flow__handle,[data-test-id*="handle"]'),
        classes};
    },{x,y});
    if(hit.node!==added.name||hit.noDrag||hit.handle){
      dragAttempts.push({fx,fy,hit,skipped:'not a draggable node surface'});
      continue;
    }
    await page.mouse.move(x,y);
    await page.mouse.down({button:'left'});
    await page.mouse.move(x+96,y+60,{steps:24});
    await page.mouse.up({button:'left'});
    try{
      movedPosition=await poll('custom node drag server autosave',async()=>{
        const w=(await api('GET','/rest/workflows/'+id)).data;
        const p=w?.nodes?.find(n=>n.id===added.id)?.position;
        return p&&Math.abs(p[0]-originalPosition[0])>30&&
          Math.abs(p[1]-originalPosition[1])>20?p:null;
      },9000);
      dragAttempts.push({fx,fy,hit,result:'persisted',position:movedPosition});
      break;
    }catch(error){
      const current=(await api('GET','/rest/workflows/'+id)).data.nodes.find(n=>n.id===added.id)?.position;
      dragAttempts.push({fx,fy,hit,current,error:error.message});
      await page.screenshot({path:path.join(OUT,'drag-attempt-'+dragAttempts.length+'.png'),fullPage:true});
    }
    // Avoid retrying a stale rectangle if the actual node has moved.
    await page.waitForTimeout(250);
  }
  // Playwright dragTo is another genuine Chrome pointer sequence (not an
  // API/DOM coordinate edit). It first selects the node and drags from the
  // node body into an empty area of the official Vue Flow pane. This covers
  // versions where a raw mouse.down on a hovered node is not enough to enter
  // the Vue Flow node-drag state.
  if(!movedPosition){
    const pane=page.locator('.vue-flow__pane');
    const box=await nodeElement.boundingBox(),paneBox=await pane.boundingBox();
    assert(box&&paneBox,'Native dragTo fallback has no visible node/pane');
    const sourcePosition={x:Math.round(box.width*.5),y:Math.round(box.height*.5)};
    const targetPosition={
      x:Math.round(Math.min(paneBox.width-25,Math.max(25,box.x+sourcePosition.x-paneBox.x+135))),
      y:Math.round(Math.min(paneBox.height-25,Math.max(25,box.y+sourcePosition.y-paneBox.y+85)))
    };
    const hit=await page.evaluate(({box,paneBox,targetPosition})=>{
      const el=document.elementFromPoint(paneBox.x+targetPosition.x,paneBox.y+targetPosition.y);
      return {tag:el?.tagName||null,node:el?.closest('.vue-flow__node')?.getAttribute('data-node-name')||null,
        onPane:!!el?.closest('.vue-flow__pane')};
    },{box,paneBox,targetPosition});
    if(hit.onPane&&!hit.node){
      try{
        await nodeElement.click({position:sourcePosition,timeout:12000});
        await nodeElement.dragTo(pane,{sourcePosition,targetPosition,timeout:20000});
        movedPosition=await poll('native Playwright dragTo server autosave',async()=>{
          const w=(await api('GET','/rest/workflows/'+id)).data;
          const p=w?.nodes?.find(n=>n.id===added.id)?.position;
          return p&&Math.abs(p[0]-originalPosition[0])>30&&
            Math.abs(p[1]-originalPosition[1])>20?p:null;
        },25000);
        dragAttempts.push({method:'native-dragTo',sourcePosition,targetPosition,hit,result:'persisted',position:movedPosition});
      }catch(error){
        const current=(await api('GET','/rest/workflows/'+id)).data.nodes.find(n=>n.id===added.id)?.position;
        dragAttempts.push({method:'native-dragTo',sourcePosition,targetPosition,hit,current,error:String(error)});
        await page.screenshot({path:path.join(OUT,'dragTo-fallback-failure.png'),fullPage:true});
      }
    }else{
      dragAttempts.push({method:'native-dragTo',sourcePosition,targetPosition,hit,skipped:'target is not empty Vue Flow pane'});
    }
  }
  assert(movedPosition,'Custom node real Chrome drag did not persist: '+JSON.stringify(dragAttempts));
  await record('real-chrome-custom-node-drag-server-coordinate-save','PASS',{
    nodeId:added.id,before:originalPosition,after:movedPosition
  });
  await page.reload({waitUntil:'domcontentloaded'});
  await nodeElement.waitFor({timeout:30000});
  const movedReload=(await api('GET','/rest/workflows/'+id)).data.nodes.find(n=>n.id===added.id);
  assert(JSON.stringify(movedReload?.position)===JSON.stringify(movedPosition),
    'Custom node coordinates changed on browser reopen');
  assert(movedReload.parameters?.operationId==='N02'&&
    movedReload.parameters?.evidenceHandling==='hold',
    'Custom node setting or HOLD policy lost after coordinate move and reload');
  await record('real-chrome-custom-node-position-and-setting-reopen','PASS',{
    nodeId:added.id,position:movedReload.position,operationId:movedReload.parameters.operationId,
    evidenceHandling:movedReload.parameters.evidenceHandling
  });
  await page.screenshot({path:path.join(OUT,'03-reopened.png'),fullPage:true});

  // Exercise the real native n8n handle drag on BOTH custom-node outputs.
  async function connectHandle(source,target){
    await source.waitFor({timeout:20000});
    await target.waitFor({timeout:20000});
    const s=await source.boundingBox(),t=await target.boundingBox();
    assert(s&&t,'Custom node output or target handle not visible');
    await page.mouse.move(s.x+s.width/2,s.y+s.height/2);
    await page.mouse.down({button:'left'});
    await page.mouse.move(t.x+t.width/2,t.y+t.height/2,{steps:18});
    await page.mouse.up({button:'left'});
  }
  const handles=nodeElement.getByTestId('canvas-node-output-handle');
  assert(await handles.count()===2,'Custom node has fewer than two UI output handles');
  for(const [index,targetName] of [[0,'Accepted Sink'],[1,'Hold Sink']]){
    const target=page.locator(
      '[data-node-name="'+targetName+'"] [data-test-id="canvas-node-input-handle"]').first();
    await connectHandle(handles.nth(index),target);
    await poll('custom output '+index+' saved',async()=>{
      const w=(await api('GET','/rest/workflows/'+id)).data;
      return w?.connections?.[added.name]?.main?.[index]?.some(
        e=>e.node===targetName&&e.type==='main'&&e.index===0);
    });
    await record('real-chrome-custom-output-'+index+'-connected','PASS',{
      outputIndex:index,target:targetName});
  }
  await page.screenshot({path:path.join(OUT,'03b-two-output-edges.png'),fullPage:true});
  await page.reload({waitUntil:'domcontentloaded'});
  await nodeElement.waitFor({timeout:30000});
  const withEdges=(await api('GET','/rest/workflows/'+id)).data;
  assert(withEdges.connections?.[added.name]?.main?.[0]?.some(e=>e.node==='Accepted Sink'),'Success edge not persisted');
  assert(withEdges.connections?.[added.name]?.main?.[1]?.some(e=>e.node==='Hold Sink'),'Hold edge not persisted');
  await record('real-chrome-custom-dual-edge-reopen','PASS',{nodeId:added.id});

  await nodeElement.hover();
  await nodeElement.getByTestId('delete-node-button').click({timeout:15000});
  await poll('custom node deletion saved',async()=>{
    const w=(await api('GET','/rest/workflows/'+id)).data;
    return !w?.nodes?.some(n=>n.id===added.id);
  });
  const afterDelete=(await api('GET','/rest/workflows/'+id)).data;
  const nodeAbsent=!afterDelete.nodes.some(n=>n.id===added.id);
  const danglingEdges=!!afterDelete.connections?.[added.name]||
    Object.values(afterDelete.connections||{}).some(byType=>
      Object.values(byType||{}).some(ports=>
        (ports||[]).some(targets=>
          (targets||[]).some(target=>target.node===added.name))));
  assert(nodeAbsent,'Deleted node unexpectedly persisted after reload');
  assert(!danglingEdges,'Deleted node left dangling inbound/outbound edges');
  await record('real-chrome-custom-node-delete-and-server-save','PASS',{
    id:added.id,nodeAbsent,danglingEdges
  });
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
         bidNo:'R26BK01787028',evidenceHandling:'hold'}},
      {id:'hold-accepted-sink',name:'Accepted Runtime Sink',
       type:'n8n-nodes-base.code',typeVersion:2,
       position:[750,70],parameters:{mode:'runOnceForAllItems',
         jsCode:'return $input.all();'}},
      {id:'hold-rejected-sink',name:'Hold Runtime Sink',
       type:'n8n-nodes-base.code',typeVersion:2,
       position:[750,340],parameters:{mode:'runOnceForAllItems',
         jsCode:'return $input.all();'}}
    ],
    connections:{
      'Manual Trigger':{main:[[
        {node:'Business Operation',type:'main',index:0}
      ]]},
      'Business Operation':{main:[
        [{node:'Accepted Runtime Sink',type:'main',index:0}],
        [{node:'Hold Runtime Sink',type:'main',index:0}]
      ]}
    },settings:{executionOrder:'v1'},staticData:null,pinData:{}
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
    // Verify the actual n8n execution graph, not just the custom node's
    // return arrays: a HOLD must execute its downstream HOLD sink and must
    // NEVER execute the success/accepted sink.
    const holdSink=runData?.['Hold Runtime Sink']?.[0]?.data?.main?.[0]||[];
    if(!output||d.status==='running'||!holdSink.length)return null;
    assert(d.status==='success','Synthetic HOLD execution did not finish successfully');
    // Per-node debugging must prove the actual native trigger INPUT path and
    // exact HOLD OUTPUT propagation, not just an execution-level green status.
    const triggerItems=runData?.['Manual Trigger']?.[0]?.data?.main?.[0]||[];
    assert(triggerItems.length===1,'Native manual trigger input item missing');
    assert(nodeRun?.data?.main?.length===2,
      'Native Business Operation did not expose both debug output ports');
    assert(JSON.stringify(holdSink[0]?.json)===JSON.stringify(output),
      'Downstream HOLD sink altered the native node debug output');
    assert(!runData?.['Accepted Runtime Sink']?.length,
      'Synthetic HOLD unexpectedly executed the accepted downstream branch');
    assert(holdSink.length===1,'Synthetic HOLD downstream sink received wrong item count');
    assert(holdSink[0]?.json?.inspection_status==='HOLD',
      'HOLD downstream sink lost fail-closed verdict');
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
      acceptedSinkExecuted:false,holdSinkExecuted:true,
      holdSinkItemCount:holdSink.length,
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
  const inspectionSchemas=createInspectionEnvelopeSchemas(manifest);
  const schemaById=new Map(inspectionSchemas.schemas.map(s=>[s.operationId,s.outputItem]));
  const manifestById=new Map(manifest.blocks.map(b=>[b.id,b]));
  const flowOwner=new Map(manifest.flows.flatMap(f=>
    f.owned_blocks.map(blockId=>[blockId,f.id])));
  assert(schemaById.size===43,'43 strict inspection schemas missing');
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
      // Cross-check the REAL native n8n execution output against the strict
      // generated inspection envelope for each manifest operation. This is
      // still synthetic HOLD verification, not a business handler acceptance.
      const schema=schemaById.get(n.parameters.operationId);
      const block=manifestById.get(n.parameters.operationId);
      assert(schema&&block,n.name+' strict inspection schema missing');
      assert(JSON.stringify(Object.keys(item).sort())===
        JSON.stringify(Object.keys(schema.properties).sort()),
        n.name+' emitted missing or extra output fields');
      for(const [key,property] of Object.entries(schema.properties)){
        if(Object.hasOwn(property,'const'))
          assert(JSON.stringify(item[key])===JSON.stringify(property.const),
            n.name+' strict constant mismatch: '+key);
      }
      assert(item.flow_id===flowOwner.get(block.id),n.name+' wrong flow owner');
      assert(JSON.stringify(item.feature_ids)===JSON.stringify(block.features),
        n.name+' feature contract changed');
      assert(item.inspection_status==='HOLD'&&item.output===null,
        n.name+' strict HOLD output must be null');
      assert(Array.isArray(item.missing_evidence)&&
        item.missing_evidence.every(key=>
          schema.properties.missing_evidence.items.enum.includes(key)),
        n.name+' unapproved evidence diagnostics');
    }
    assert(d.status==='success','43-operation native n8n run failed: '+d.status);
    return {executionId:allExecutionId,nativeOperations:allNodes.length,
      holdOutputs:allNodes.length,successOutputs:0,status:d.status,
      realBusinessHandlers:0,actualBidSubmitted:false,
      strictInspectionEnvelopesValidated:43};
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
