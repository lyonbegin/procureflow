import assert from 'node:assert/strict';
import {chromium} from 'playwright';
const base=process.env.STUDIO_BASE||'http://127.0.0.1:3031';
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{
 const ctx=await browser.newContext({viewport:{width:1500,height:970}});
 const page=await ctx.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(!r.url().startsWith(base+'/')&&!r.url().startsWith('data:'))errors.push('Unexpected external request '+r.url());});
 await page.goto(base+'/admin/index.html?section=overview',{waitUntil:'domcontentloaded'});
 await page.locator('#side-menu .nav').first().waitFor({timeout:15000});
 assert.equal(await page.locator('#side-menu .nav').count(),11);
 await page.waitForFunction(()=>document.body.innerText.includes('R26BK01787028')&&document.body.innerText.includes('104개 업무'),{timeout:30000});
 await page.locator('[data-page="opportunities"]').first().click();
 assert.match(await page.locator('#content').innerText(),/선택된 입찰공고/);
 await page.locator('[data-page="tests"]').first().click();
 await page.getByRole('button',{name:/PF 전체 43블록/}).waitFor({timeout:10000});
 await page.locator('[data-public-action="all"]').click();
 await page.waitForFunction(()=>document.body.innerText.includes('43/43')&&document.body.innerText.includes('HOLD_OFFICIAL_EVIDENCE'),{timeout:120000});
 assert.equal(await page.locator('[data-public-action="inspect"]').count(),43);
 await page.locator('[data-public-action="inspect"][data-node="public-H07"]').click();
 assert.match(await page.locator('#content').innerText(),/121/);
 await page.locator('[data-page="strategy"]').first().click();
 assert.match(await page.locator('#content').innerText(),/10년/);
 assert.match(await page.locator('#content').innerText(),/제안서/);
 const catalog=await (await ctx.request.get(base+'/public-case-feature-catalog.json')).json();
 const verified={
   source_provenance:'live_procureflow_postgresql_verified_evidence',
   bid_no:'R26BK01787028',bid_ord:'000',
   business_blocks_checked:43,features_checked:104,
   features_officially_verified:0,eligible_for_manual_bid_participation:false,
   automatic_bid_submission:false,actual_job_executed:false,
   features:catalog.features.map(x=>({number:x.number,acceptance_state:'missing'})),
   blocks:catalog.manifest_blocks.map(x=>({id:x.id,name:x.label,status:'blocked',missing_evidence:['official_evidence_missing']}))
 };
 await page.route('**/api/procurement/public/verified-evidence',route=>route.fulfill({
   status:200,contentType:'application/json',body:JSON.stringify(verified)
 }));
 await page.locator('[data-page="public"]').first().click();
 await page.locator('[data-public-action="load-verified"]').first().click();
 await page.waitForFunction(()=>document.body.innerText.includes('운영 PostgreSQL은')&&document.body.innerText.includes('0개 기능'),{timeout:20000});
 await page.locator('[data-page="features"]').first().click();
 await page.waitForFunction(()=>document.querySelectorAll('#content tbody tr').length>=104,{timeout:20000});
 const featureRows=await page.locator('#content tbody tr').allInnerTexts();
 assert.equal(featureRows.filter(v=>/^F\d{3}\b/.test(v.trim())).length,104); // actual F001-F104, plus original 43 block/evidence rows
 assert.equal(await page.locator('#content tbody tr:has-text("F104")').count(),1);
 assert.match(await page.locator('#content').innerText(),/공식 미검증/);
 await page.locator('[data-page="audit"]').first().click();
 await page.locator('[data-public-action="history"]').first().click();
 await page.waitForFunction(()=>document.body.innerText.includes('43개')&&document.body.innerText.includes('public-O04'),{timeout:15000});
 await page.reload({waitUntil:'domcontentloaded'});
 await page.waitForFunction(()=>document.querySelectorAll('[data-public-action="history"]').length>=1,{timeout:30000});
 assert.deepEqual(errors,[]);
 console.log('PUBLIC_SELECTED_TENDER_ORIGINAL_43_BLOCK_104_FEATURE_CHROME_E2E_PASS_NO_REAL_G2B');
 await ctx.close();
}finally{await browser.close();}
