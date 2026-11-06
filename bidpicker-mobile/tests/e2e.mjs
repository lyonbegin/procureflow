import assert from 'node:assert/strict';
import {chromium} from 'playwright';
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const page=await browser.newPage({viewport:{width:390,height:844},deviceScaleFactor:1,isMobile:true,hasTouch:true});
const errors=[],queries=[],jobs=new Map();
page.on('pageerror',e=>errors.push(e.message));
const origin='http://127.0.0.1:8080/';
function check(condition,text){assert.ok(condition,text);console.log('UI_PASS',text)}
const rows=[
 {id:'R26BM01032422-000',bidNo:'R26BM01032422',bidSeq:'000',
   title:'세종시 도서관 ICT 통합정보시스템 유지관리 용역',agencyName:'조달청',
   region:'',status:'',source:'g2b_live_official_site'},
 {id:'R26BM01032671-000',bidNo:'R26BM01032671',bidSeq:'000',
   title:'우장산역 노후 에스컬레이터 교체공사',agencyName:'서울교통공사',
   region:'서울',status:'',source:'g2b_live_official_site'}
];
let index=0;
await page.route('**/api/bidpicker/discover?**',async route=>{
 const q=new URL(route.request().url()).searchParams;
 queries.push({keyword:q.get('keyword')||'',region:q.get('region')||'전국'});
 const id=(++index).toString(16).padStart(32,'0');
 jobs.set(id,{keyword:q.get('keyword')||'',region:q.get('region')||'전국'});
 await route.fulfill({status:202,contentType:'application/json',
  body:JSON.stringify({jobId:id,status:'queued',source:'g2b_live_official_site',db_reads:0})});
});
await page.route('**/api/bidpicker/live/jobs/*',async route=>{
 const id=route.request().url().split('/').at(-1),q=jobs.get(id);
 if(!q)return route.fulfill({status:404,contentType:'application/json',body:'{}'});
 const items=rows.filter(x=>(!q.keyword||x.title.includes(q.keyword)||x.agencyName.includes(q.keyword))&&
   (q.region==='전국'||x.region===q.region));
 await route.fulfill({status:200,contentType:'application/json',
  body:JSON.stringify({status:'completed',items,total:items.length,hasMore:false,
   source:'g2b_live_official_site',db_reads:0,live_search_verified:true,
   filterNotes:['매번 나라장터 사이트에 새로 요청하는 테스트 흐름입니다.']})});
});
await page.route('**/api/bidpicker/status',route=>route.fulfill({status:200,contentType:'application/json',
 body:JSON.stringify({status:'live_only',db_reads:0})}));
try{
 await page.goto(origin,{waitUntil:'domcontentloaded'});
 await page.locator('.onboard-top button').click();
 check(await page.locator('.bottom-item').count()===5,'5 original tabs present');
 check(await page.locator('.category-tile').count()===8,'8 categories present');
 await page.locator('.bottom-item').nth(1).click();
 await page.waitForSelector('.search-box');
 await page.locator('.search-box input').fill('정보시스템');
 await page.locator('.search-submit').click();
 await page.waitForSelector('.cards-list .bid-card',{timeout:18000});
 check((await page.locator('.bid-card h3').first().textContent()).includes('정보시스템'),'live POST job result visibly renders in mobile UI');
 check(queries.at(-1).keyword==='정보시스템','search keyword actually reaches live job start');
 await page.locator('.search-box input').fill('');
 await page.locator('.search-submit').click();
 await page.waitForFunction(()=>document.querySelectorAll('.bid-card').length===2,{timeout:18000});
 await page.locator('.quick-filters .chip').first().click();
 await page.waitForSelector('.popup .chip-flow');
 await page.locator('.popup .chip-flow .chip').filter({hasText:'서울'}).first().click();
 await page.waitForFunction(()=>document.querySelectorAll('.bid-card').length===1,{timeout:18000});
 check(queries.at(-1).region==='서울','region selection starts another fresh official G2B query');
 check((await page.locator('.bid-card h3').first().textContent()).includes('우장산역'),'regional result visibly rendered');
 check((await page.locator('.bid-card .status-chip').first().textContent()).includes('상태 확인중'),'unknown source status not fabricated');
 await page.locator('.bottom-item').nth(2).click();await page.waitForSelector('.saved-page');
 await page.locator('.bottom-item').nth(3).click();await page.waitForSelector('.alerts-page');
 await page.locator('.bottom-item').nth(4).click();await page.waitForSelector('.settings-page');
 check(errors.length===0,'zero runtime JS errors');
 check(queries.length>=3,'each search creates a new live job');
 console.log('UI_E2E_COMPLETED');
}catch(e){console.error('UI_E2E_FAILED',e);throw e}finally{await browser.close()}
