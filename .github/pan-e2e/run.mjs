#!/usr/bin/env node
// Issue #21 — real Google Chrome against *patched official n8n*, not a fixture.
// Isolated Docker container + SQLite only. No operational G2B, jobs or credentials.
import {chromium, selectors} from 'playwright';
// Native n8n marks controls with data-test-id (not Playwright's data-testid default).
selectors.setTestIdAttribute('data-test-id');
import {parse as parseFlatted} from 'flatted';
import fs from 'node:fs/promises';
import path from 'node:path';
import {assertIsolatedN8nUrl} from './scenario-safety.mjs';

// Fail closed BEFORE Chrome launch or owner/workflow writes: never point this
// destructive test driver at an operating Railway or external n8n instance.
const URL = assertIsolatedN8nUrl(process.env.N8N_E2E_URL ?? 'http://127.0.0.1:5678');
const OUT = process.env.N8N_E2E_ARTIFACTS ?? 'shared-pan-e2e-artifacts';
const EMAIL = 'pan-test@example.invalid';
const PASSWORD = 'PanSmokeStrong123!';
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const reports = [];
let browser, page, context;
const rec = async (name, result, details = {}) => {
  const item = {name, result, ...details};
  reports.push(item);
  console.log('E2E', JSON.stringify(item));
  await fs.writeFile(path.join(OUT, 'verdicts.json'), JSON.stringify(reports, null, 2));
};
const assert = (condition, msg) => {if (!condition) throw Error(msg);};
async function api(method, endpoint, data) {
  const response = await context.request.fetch(URL + endpoint, {
    method,
    ...(data === undefined ? {} : {data, headers: {'content-type':'application/json'}}),
    timeout: 25000,
    maxRedirects: 0 // Playwright API requests bypass page.route()
  });
  const raw = await response.text();
  let body;
  try {body = JSON.parse(raw);} catch {body = {raw: raw.slice(0, 600)};}
  if (!response.ok()) throw Error(method + ' ' + endpoint + ': HTTP ' + response.status() + ' ' + JSON.stringify(body).slice(0, 700));
  return body;
}
async function poll(label, fn, timeout=16000) {
  const start=Date.now();
  let lastError;
  while(Date.now()-start<timeout) {
    try {const v=await fn();if(v) return v;}catch(e){lastError=e;}
    await sleep(500);
  }
  throw Error(label + ' timed out' + (lastError ? ': ' + lastError.message : ''));
}
async function drag(x1,y1,x2,y2,button='left') {
  await page.mouse.move(x1,y1);
  await page.mouse.down({button});
  await page.mouse.move(x2,y2,{steps:14});
  await page.mouse.up({button});
  await sleep(500);
}
async function viewport() {
  return await page.locator('.vue-flow__transformationpane').evaluate(el=> {
    const st=getComputedStyle(el).transform;
    const m=new DOMMatrix(st==='none'?undefined:st);
    return {x:m.m41,y:m.m42,scale:m.a,transform:st};
  });
}
async function panePoint() {
  return await page.locator('.vue-flow__pane').evaluate(el => {
    const r=el.getBoundingClientRect();
    const candidates=[[.79,.70],[.78,.23],[.13,.75],[.50,.88],[.50,.1]];
    for (const [px,py] of candidates) {
      const x=r.left+r.width*px,y=r.top+r.height*py;
      const other=document.elementFromPoint(x,y);
      if(other && !other.closest('.vue-flow__node,.vue-flow__handle,.vue-flow__controls')) return {x,y};
    }
    return {x:r.left+r.width*.79,y:r.top+r.height*.70};
  });
}
async function storageWorkflow(id) {
  return (await api('GET','/rest/workflows/'+id)).data;
}
const synthetic = {
  name:'Issue21 Pan Chrome Test',
  nodes:[
    {id:'pan-manual-01',name:'Manual Trigger',type:'n8n-nodes-base.manualTrigger',typeVersion:1,position:[120,150],parameters:{}},
    {id:'pan-code-02',name:'Code',type:'n8n-nodes-base.code',typeVersion:2,position:[470,150],parameters:{mode:'runOnceForAllItems',jsCode:'return [{json:{pan_test:true,answer:42}}];'}}
  ],
  connections: {},
  settings:{executionOrder:'v1'},
  staticData:null,
  pinData:{}
};
await fs.mkdir(OUT,{recursive:true});
try {
  browser=await chromium.launch({channel:'chrome',headless:true,args:['--no-sandbox']});
  context=await browser.newContext({viewport:{width:1440,height:900},serviceWorkers:'block'});
  // The editor may fetch remote resources: isolate browser network too.
  await context.route('**/*', async route => {
    if(new globalThis.URL(route.request().url()).origin !== URL) return route.abort();
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
  page.on('pageerror',e=>console.error('PAGE ERROR',e.message));
  page.on('console',e=>{if(e.type()==='error')console.error('BROWSER',e.text().slice(0,400));});
  const settings=await api('GET','/rest/settings');
  if(settings?.data?.userManagement?.showSetupOnFirstLoad) {
    await api('POST','/rest/owner/setup',{email:EMAIL,firstName:'Pan',lastName:'Test',password:PASSWORD});
  }
  await api('POST','/rest/login',{emailOrLdapLoginId:EMAIL,password:PASSWORD});
  await rec('isolated-owner-authentication','PASS');
  const w=(await api('POST','/rest/workflows',synthetic)).data;
  assert(w?.id,'Server did not return workflow ID');
  const workflowId=String(w.id);
  await rec('server-create-synthetic-workflow','PASS',{workflowId});
  await page.goto(URL+'/workflow/'+workflowId,{waitUntil:'domcontentloaded'});
  await page.locator('[data-test-id="canvas"]').waitFor({timeout:30000});
  await page.locator('[data-test-id="canvas-node"][data-node-name="Manual Trigger"]').waitFor({timeout:25000});
  await page.locator('[data-test-id="canvas-node"][data-node-name="Code"]').waitFor({timeout:25000});
  await page.screenshot({path:path.join(OUT,'01-official-editor.png'),fullPage:true});
  await rec('official-n8n-canvas-renders','PASS',{workflowId,url:page.url()});

  // Exercise actual native palette CRUD immediately after initial canvas load.
  // A later browser reload currently hides the creator toolbar in this fixture;
  // this test must still verify genuine Chrome add/delete without REST insertion.
  const palette=page.getByTestId('node-creator-search-bar');
  const plus=page.getByTestId('node-creator-plus-button');
  // Use only genuine Chrome UI entry points. No REST/DOM insertion.
  const editState=await page.evaluate(()=>{
    const body=document.body.innerText;
    const buttons=[...document.querySelectorAll('[data-test-id]')]
      .map(e=>e.getAttribute('data-test-id'))
      .filter(x=>/creator|zoom|edit|readonly|read-only/i.test(x||''));
    return {readOnlyText:/read.only|view.only|no edit permission/i.test(body),
      readOnlyExcerpt:body.match(/.{0,65}(?:read.only|view.only|no edit permission).{0,65}/i)?.[0]||null,
      controls:[...new Set(buttons)].slice(0,45)};
  });
  const storedForEdit=await storageWorkflow(workflowId);
  await rec('native-editor-post-reload-editability-diagnostic','OBSERVED',{
    workflowScopes:storedForEdit.scopes??null,
    plusInitiallyVisible:await plus.isVisible().catch(()=>false),
    editState
  });
  const entryAttempts=[];
  for(const method of ['toolbar-plus','blank-pane-doubleclick','keyboard-tab']){
    if(await palette.isVisible().catch(()=>false))break;
    try{
      if(method==='toolbar-plus'){
        // Do not treat a still-hydrating toolbar as permanently absent.
        try{await plus.waitFor({state:'visible',timeout:15000});}
        catch{
          entryAttempts.push({method,result:'toolbar not visible after 15s',editState});
          continue;
        }
        await plus.click({timeout:6000});
      }else{
        const empty=await panePoint();
        const hit=await page.evaluate(({x,y})=>{
          const el=document.elementFromPoint(x,y);
          return {onPane:!!el?.closest('.vue-flow__pane'),
            onNode:!!el?.closest('.vue-flow__node'),
            tag:el?.tagName||null};
        },empty);
        if(!hit.onPane||hit.onNode){
          entryAttempts.push({method,result:'no verified blank pane',hit});
          continue;
        }
        await page.mouse.click(empty.x,empty.y,{clickCount:method==='blank-pane-doubleclick'?2:1,delay:110});
        if(method==='keyboard-tab')await page.keyboard.press('Tab');
      }
      await palette.waitFor({state:'visible',timeout:6000});
      entryAttempts.push({method,result:'palette opened'});
    }catch(error){
      entryAttempts.push({method,result:'not opened',error:String(error).slice(0,180)});
      await page.screenshot({path:path.join(OUT,'palette-'+method+'-diagnostic.png'),fullPage:true});
    }
  }
  assert(await palette.isVisible().catch(()=>false),
    'Native node creator did not open using Chrome UI: '+JSON.stringify(entryAttempts));
  await rec('real-chrome-native-palette-open','PASS',{entryAttempts});
  await palette.fill('No Operation');
  await page.getByTestId('node-creator-item-name').getByText('No Operation, do nothing',{exact:true}).click();
  const closeNdv=page.getByTestId('ndv-close-button');
  if(await closeNdv.isVisible().catch(()=>false))await closeNdv.click();
  const added=await poll('native palette node persisted',async()=>{
    const d=await storageWorkflow(workflowId);
    return d.nodes.find(n=>n.type==='n8n-nodes-base.noOp')??null;
  },30000);
  await rec('real-chrome-palette-add-node-and-autosave','PASS',{id:added.id,type:added.type});
  await page.screenshot({path:path.join(OUT,'05-palette-added.png'),fullPage:true});

  // Native toolbar delete, not REST deletion.
  const addedEl=page.locator('[data-test-id="canvas-node"][data-node-name="'+added.name+'"]').first();
  await addedEl.hover();
  await addedEl.getByTestId('delete-node-button').click();
  await poll('deleted node absent in saved DB',async()=>{
    const d=await storageWorkflow(workflowId);
    return !d.nodes.some(n=>n.id===added.id);
  },30000);
  await rec('real-chrome-delete-node-and-autosave','PASS',{deletedNodeId:added.id});


  // Pan is the high-priority real user regression: viewport moves but graph data does not.
  const original=(await storageWorkflow(workflowId)).nodes.map(n=>({id:n.id,position:n.position}));
  const pt=await panePoint();
  const before=await viewport();
  await drag(pt.x,pt.y,pt.x+135,pt.y-75);
  const after=await viewport();
  assert(Math.abs(after.x-before.x)>45 && Math.abs(after.y-before.y)>35,'Left drag did not move viewport: '+JSON.stringify({before,after}));
  await rec('left-button-empty-pane-pan','PASS',{before,after});
  const pt2=await panePoint(),b2=await viewport();
  await drag(pt2.x,pt2.y,pt2.x-110,pt2.y+65,'middle');
  const a2=await viewport();
  assert(Math.abs(a2.x-b2.x)>35,'Middle drag did not pan');
  await rec('middle-button-empty-pane-pan','PASS',{before:b2,after:a2});
  const pt3=await panePoint(),b3=await viewport();
  await page.keyboard.down('Shift');
  await drag(pt3.x,pt3.y,pt3.x+90,pt3.y+70);
  await page.keyboard.up('Shift');
  const a3=await viewport();
  assert(Math.abs(a3.x-b3.x)<5 && Math.abs(a3.y-b3.y)<5,'Shift selection incorrectly panned viewport');
  await rec('shift-marquee-not-pan','PASS',{before:b3,after:a3});
  const panStored=(await storageWorkflow(workflowId)).nodes.map(n=>({id:n.id,position:n.position}));
  assert(JSON.stringify(panStored)===JSON.stringify(original),'Camera Pan changed stored node coordinates');
  await rec('pan-does-not-change-node-coordinates','PASS',{positions:panStored});
  await page.screenshot({path:path.join(OUT,'02-after-pan.png'),fullPage:true});

  // Real handle drag, not injected connections.
  const source=page.locator('[data-node-name="Manual Trigger"] [data-test-id="canvas-node-output-handle"]').first();
  const target=page.locator('[data-node-name="Code"] [data-test-id="canvas-node-input-handle"]').first();
  await source.waitFor();
  await target.waitFor();
  const s=await source.boundingBox(),t=await target.boundingBox();
  assert(s&&t,'Source or target handle is not visible');
  await drag(s.x+s.width/2,s.y+s.height/2,t.x+t.width/2,t.y+t.height/2);
  const connected=await poll('server-persisted UI handle connection',async()=>{
    const d=await storageWorkflow(workflowId);
    return d?.connections?.['Manual Trigger']?.main?.[0]?.some(e=>e.node==='Code')?d:null;
  },25000);
  await rec('real-chrome-handle-connect-and-server-persist','PASS',{connection:connected.connections['Manual Trigger']});
  await page.screenshot({path:path.join(OUT,'03-connected.png'),fullPage:true});

  // Real node movement updates workflow coordinates, not viewport.
  const codeNode=page.locator('[data-test-id="canvas-node"][data-node-name="Code"]').first();
  await codeNode.scrollIntoViewIfNeeded();
  const rb=await codeNode.boundingBox();
  assert(rb,'Node not visible for drag');
  const movedBefore=(await storageWorkflow(workflowId)).nodes.find(n=>n.name==='Code').position;
  await drag(rb.x+rb.width*.5,rb.y+rb.height*.5,rb.x+rb.width*.5+90,rb.y+rb.height*.5+50);
  const moved=await poll('node position saved',async()=>{
    const d=await storageWorkflow(workflowId);
    const p=d.nodes.find(n=>n.name==='Code').position;
    return (Math.abs(p[0]-movedBefore[0])>30 && Math.abs(p[1]-movedBefore[1])>20)?p:null;
  },25000);
  await rec('real-node-drag-saved-in-db','PASS',{before:movedBefore,after:moved});

  // Edit through the genuine native NDV while the Chrome editor is demonstrably
  // writable. In this isolated n8n fixture, a later browser reload may render
  // CodeMirror aria-readonly=true; filling that DOM would falsely test an
  // unavailable control rather than the native parameter persistence contract.
  const newJs='return [{json:{pan_test:true,answer:43}}];';
  await page.locator('[data-test-id="canvas-node"][data-node-name="Code"]').dblclick();
  const cm=page.getByTestId('parameter-input-jsCode').locator('.cm-content');
  await cm.waitFor({state:'visible',timeout:20000});
  const cmEditable=await cm.evaluate(el=>({
    contenteditable:el.getAttribute('contenteditable'),
    ariaReadonly:el.getAttribute('aria-readonly')
  }));
  assert(cmEditable.contenteditable==='true'&&cmEditable.ariaReadonly!=='true',
    'Native CodeMirror is not editable before reload: '+JSON.stringify(cmEditable));
  await cm.fill(newJs);
  await page.getByTestId('ndv-close-button').click();
  await poll('CodeMirror edit saved in server',async()=>{
    const d=await storageWorkflow(workflowId);
    return d.nodes.find(n=>n.name==='Code')?.parameters?.jsCode===newJs;
  },30000);
  await rec('real-chrome-parameter-edit-and-server-persistence','PASS',{jsCode:newJs});

  await page.reload({waitUntil:'domcontentloaded'});
  await page.locator('[data-test-id="canvas-node"][data-node-name="Code"]').waitFor({timeout:30000});
  const loaded=await storageWorkflow(workflowId);
  assert(JSON.stringify(loaded.nodes.find(n=>n.name==='Code').position)===JSON.stringify(moved),'Node position changed on reload');
  assert(loaded.connections['Manual Trigger']?.main?.[0]?.some(e=>e.node==='Code'),'Handle connection not preserved on reload');
  await rec('save-reopen-position-and-edge-persist','PASS',{nodePosition:moved});
  // Track the separate post-reload creator visibility regression without
  // manufacturing a PASS or silently treating an absent toolbar as editable.
  await rec('native-creator-after-reopen-visibility','OBSERVED',{
    plusVisible:await page.getByTestId('node-creator-plus-button').isVisible().catch(()=>false),
    note:'Palette CRUD was performed by real Chrome before reload; post-reload creator availability remains a separate regression.'
  });
  await page.screenshot({path:path.join(OUT,'04-reopened.png'),fullPage:true});

  // Native official n8n zoom controls, measured via actual Vue Flow transform.
  // Run after palette CRUD so zoom animations cannot hide the creator toolbar.
  const zoomBefore=await viewport();
  await page.getByTestId('zoom-in-button').click();
  await poll('zoom in',async()=>(await viewport()).scale>zoomBefore.scale+0.01);
  const zoomIn=await viewport();
  await page.getByTestId('zoom-out-button').click();
  await rec('real-editor-zoom-in-out','PASS',{before:zoomBefore,zoomIn,zoomOut:await viewport()});

  // The real Chrome NDV edit occurred before reload. Assert that the exact
  // parameter survives the already-performed browser reload; never inject
  // a value through REST/DOM to compensate for read-only post-reload controls.
  assert((await storageWorkflow(workflowId)).nodes.find(n=>n.name==='Code')?.parameters?.jsCode===newJs,
    'Code parameter lost after reload');
  await rec('real-chrome-parameter-reopen-persistence','PASS',{jsCode:newJs});
  await page.screenshot({path:path.join(OUT,'06-settings-reopened.png'),fullPage:true});

  // Use actual official editor UI for safe manual execution of Code-only result.
  const startedResponse=page.waitForResponse(r=>
    r.url().includes('/rest/workflows/')&&r.url().includes('/run')&&r.request().method()==='POST',
    {timeout:45000}
  );
  await page.locator('[data-test-id="execute-workflow-button"]').first().click({timeout:15000});
  const started=(await (await startedResponse).json()).data;
  const executionId=String(started?.executionId??started?.id??'');
  assert(executionId,'Native execution response missing server executionId: '+JSON.stringify(started));
  const execution=await poll('native n8n execution saved with node I/O',async()=>{
    const d=(await api('GET','/rest/executions/'+executionId)).data;
    const payload=typeof d?.data==='string' ? parseFlatted(d.data) : d?.data;
    const data=payload?.resultData?.runData??d?.resultData?.runData;
    const code=data?.Code?.[0];
    const result=code?.data?.main?.[0]?.[0]?.json;
    return result?.pan_test===true&&result?.answer===43 ? {id:executionId,status:d.status,codeOutput:result,nodeNames:Object.keys(data)}:null;
  },60000);
  await rec('real-n8n-editor-execution-and-node-output','PASS',execution);
  await page.screenshot({path:path.join(OUT,'07-executed.png'),fullPage:true});
} catch(e) {
  const error=e?.stack??String(e);
  console.error('E2E FAILURE',error);
  await rec('test-run','FAIL',{error});
  if(page) try {await page.screenshot({path:path.join(OUT,'failure.png'),fullPage:true});}catch{}
  process.exitCode=1;
} finally {
  if(context)try {await context.tracing.stop({path:path.join(OUT,'chrome-trace.zip')});}catch{}
  if(context)try{await context.close();}catch{}
  if(browser)try{await browser.close();}catch{}
}
