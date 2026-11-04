import assert from 'node:assert/strict';
import {chromium} from 'playwright';
const base=process.env.STUDIO_BASE||'http://127.0.0.1:3031';
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{
 const ctx=await browser.newContext({viewport:{width:1500,height:970}});
 const page=await ctx.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(!r.url().startsWith(base+'/')&&!r.url().startsWith('data:'))errors.push('Unexpected external request '+r.url());});
 const real={
  mode:'actual_existing_g2b_records',case_bid_no:'R26BK01787028',bid_ord:'000',
  title:'실제 SW 개발 공고 기록',agency:'재단법인전남테크노파크',
  deadline:'2026-10-29 10:00',configured_detail10:'8111159901',
  official_notice_verified:false,official_api_key_present:false,
  historical_period:{from:'2016-10-24',to:'2026-10-24'},
  candidate_notices_not_results:444,
  actual_counts:{verified_notice_rounds:238,opening_bidder_rows:246,
    opening_amount_rows:156,confirmed_award_rows:0},
  ten_year_coverage_complete:false,documents_downloaded:4,
  price_status:'blocked',price_missing:['cost_breakdown','price_rules','supplier_quotes'],
  actual_opening_rows:[{bid_no:'R26BK01779514',bid_ord:'000',kind:'opening',company:'주식회사 액츠원',
    amount:'168500000',rank:'1',original_evidence_url:'https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do'}],
  documents:[{filename:'1. 공고문.pdf',bytes:604491,state:'parsed',
    sha256:'a'.repeat(64),source_url:'https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/downloadFile.do'}],
  new_collection_started:false,bid_submitted:false
 };
 await page.route('**/api/procurement/public/actual-records',route=>route.fulfill({
   status:200,contentType:'application/json',body:JSON.stringify(real)
 }));
 await page.goto(base+'/admin/index.html?section=overview',{waitUntil:'domcontentloaded'});
 await page.locator('#side-menu .nav').first().waitFor({timeout:15000});
 assert.equal(await page.locator('#side-menu .nav').count(),11);
 await page.waitForFunction(()=>document.body.innerText.includes('R26BK01787028')&&document.body.innerText.includes('104개 업무'),{timeout:30000});
 await page.locator('[data-page="opportunities"]').first().click();
 assert.match(await page.locator('#content').innerText(),/실제 수집 자료/);
 await page.locator('[data-page="public"]').first().click();
 await page.waitForFunction(()=>document.body.innerText.includes('238')&&document.body.innerText.includes('246')&&document.body.innerText.includes('주식회사 액츠원'),{timeout:20000});
 assert.match(await page.locator('#content').innerText(),/공식 확정 낙찰/);
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
 assert.match(await page.locator('#content').innerText(),/공식 검증 없음/);
 assert.match(await page.locator('#content').innerText(),/missing/);
 await page.locator('[data-page="audit"]').first().click();
 await page.locator('[data-public-action="history"]').first().click();
 await page.waitForFunction(()=>document.body.innerText.includes('43개')&&document.body.innerText.includes('public-O04'),{timeout:15000});
 await page.reload({waitUntil:'domcontentloaded'});
 await page.waitForFunction(()=>document.querySelectorAll('[data-public-action="history"]').length>=1,{timeout:30000});
 assert.deepEqual(errors,[]);
 console.log('REAL_G2B_POSTGRES_EXISTING_238_246_SOURCED_UI_AND_ORIGINAL_43_104_CHROME_E2E_PASS');
 await ctx.close();
}finally{await browser.close();}
