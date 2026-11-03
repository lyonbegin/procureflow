import assert from 'node:assert/strict';
import {chromium} from 'playwright';
const base=process.env.STUDIO_BASE||'http://127.0.0.1:3031';
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{
 const ctx=await browser.newContext({viewport:{width:1536,height:1024}});
 const page=await ctx.newPage(),errors=[],calls=[];
 page.on('pageerror',e=>errors.push(e.message));
 const latest={bid_no:'R26BK01799999',bid_ord:'000',title:'신규 공고 (CI에서만 가로챈 시험응답)',
   agency:'신규 발주기관',notice_date:'2026-11-03',deadline:'2026-11-10',can_run_full_evidence:false};
 const supported={bid_no:'R26BK01787028',bid_ord:'000',title:'기존 실제 공공 용역',
   agency:'전남테크노파크',notice_date:'2026-10-22',deadline:'2026-10-29',can_run_full_evidence:true};
 const rows=[latest,supported];
 const originalWorker={job_id:1728,case_bid_no:'R26BK01787028',
    worker_job_id_is_not_n8n_execution_id:true,job_state:'completed_partial',
    actual_stages_recorded:9,
    steps:Array.from({length:9},(_,i)=>({run_id:651+i,step:'actual_stage_'+(i+1),
      state:i===6?'blocked':i===2?'partial':'verified',
      summary:{original_job:1728,actual_step:i+1},error:'',started_at:'2026-11-03T10:00:00',finished_at:'2026-11-03T10:00:01'})),
    draft:{bytes:40488,sha256:'f'.repeat(64),state:'review_draft_not_submitted'}};
 await page.route('**/api/procurement/public9/notices?*',route=>{
   calls.push({kind:'GET_NOTICES',url:route.request().url()});
   return route.fulfill({status:200,contentType:'application/json',
      body:JSON.stringify({source:'actual_procureflow_postgresql_g2b_notices',
         items:rows,total:2,default_latest_bid_no:latest.bid_no})});
 });
 await page.route('**/api/procurement/public9/latest',route=>route.fulfill({
   status:200,contentType:'application/json',body:JSON.stringify(originalWorker)}));
 await page.route('**/api/procurement/public9/job/1728',route=>route.fulfill({
   status:200,contentType:'application/json',body:JSON.stringify(originalWorker)}));
 await page.route('**/api/procurement/public9/prepare',route=>{
   const q=route.request(),payload=q.postDataJSON();
   calls.push({kind:'POST_WORKER',authorization:q.headers()['authorization'],payload});
   return route.fulfill({status:202,contentType:'application/json',
    body:JSON.stringify({job_id:1728,worker_source:'g2b_public_prepare',
        bid_submitted:false,queued:true})});
 });
 await page.goto(base+'/admin/index.html?section=public',{waitUntil:'domcontentloaded'});
 await page.waitForFunction(()=>document.querySelectorAll('#content input[name="p9-tender"]').length===2,{timeout:30000});
 assert.match(await page.locator('#content').innerText(),/최신 공고/);
 assert.match(await page.locator('#content').innerText(),/R26BK01799999/);
 assert.match(await page.locator('#content').innerText(),/R26BK01787028/);
 assert.equal(await page.locator('#content [data-public9="run"]').isDisabled(),true,
   'unsupported newest tender must never run the old selected case');
 assert.equal(await page.locator('#content').getByText('651',{exact:true}).count(),0,
   'other tender must never inherit previous Worker stage evidence');
 await page.locator('input[data-public9="choose"][data-bid="R26BK01787028"]').click();
 assert.equal(await page.locator('#content [data-public9="run"]').isEnabled(),true);
 assert.match(await page.locator('#content').innerText(),/1728/);
 await page.locator('#content [data-public9="node"][data-index="4"]').click();
 assert.match(await page.locator('#content').innerText(),/655/);
 await page.locator('#content [data-page="public_nodes"]').first().click();
 await page.locator('#content iframe[title*="9개 업무 노드"]').waitFor({timeout:12000});
 const frame=page.frameLocator('#content iframe[title*="9개 업무 노드"]');
 await frame.locator('#app').waitFor({timeout:20000});
 const editor=await ctx.request.get(base+'/api/studio/workflows/operations/PF00-public-nine-real.json');
 assert.equal(editor.status(),200);
 const w=await editor.json();
 assert.equal(w.workflow.nodes.filter(n=>n.id.startsWith('public9-0')).length,9);
 assert.equal(w.workflow.meta.real_data_only,true);
 assert.equal(w.workflow.meta.native_n8n_verified,false);
 assert.equal(w.workflow.meta.can_start_real_worker_from_this_graph,false);
 // A valid edit to REAL search-node 04 must control the actual Worker filter,
 // not merely redraw a disconnected node card. All other business code is
 // still explicitly not deployed to the official n8n Worker.
 const edited=structuredClone(w.workflow);
 const n4=edited.nodes.find(x=>x.id==='public9-04');
 n4.parameters.url=n4.parameters.url.replace('start=2016-10-24','start=2020-01-01');
 const saved=await ctx.request.put(base+'/api/studio/workflows/operations/PF00-public-nine-real.json',{
   data:{expectedVersion:w.version,workflow:edited}
 });
 assert.equal(saved.status(),200,'save real n8n source node graph first');
 const newVersion=await saved.json();
 assert.equal(newVersion.version,1);

 await page.locator('#content [data-public9="node"][data-index="7"]').click();
 assert.match(await page.locator('#content').innerText(),/658/);
 await page.locator('#content [data-page="public"]').first().click();
 await page.locator('#content #p9-token').fill('ci-only-user-admin-token');
 const realRequest=page.waitForRequest(req=>req.url().endsWith('/api/procurement/public9/prepare')&&req.method()==='POST',{timeout:20000});
 await page.locator('#content [data-public9="run"]').click();
 try{await realRequest;}catch(error){
   throw Error('Actual saved-n8n-node filter did not trigger production Worker queue: '+await page.locator('#content').innerText());
 }
 assert.equal(calls.filter(x=>x.kind==='POST_WORKER').length,1);
 const q=calls.find(x=>x.kind==='POST_WORKER');
 assert.equal(q.authorization,'Bearer ci-only-user-admin-token');
 assert.equal(q.payload.bid_no,'R26BK01787028');
 assert.equal(q.payload.detail10,'8111159901');
 assert.equal(q.payload.start,'2020-01-01');
 assert.equal(q.payload.end,'2026-10-22');
 assert.equal(q.payload.submit_bid,undefined);
 assert.equal(await page.locator('#content #p9-token').inputValue(),'');
 assert.equal(errors.length,0,'Uncaught UI errors: '+errors.join('; '));
 console.log('PROCUREFLOW_PUBLIC9_NEWEST_SELECT_ACTUAL_WORKER_NODES_ORIGINAL_STUDIO_IFRAME_CI_PASS');
}finally{await browser.close();}
