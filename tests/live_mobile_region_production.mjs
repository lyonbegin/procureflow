import assert from 'node:assert/strict';
import {chromium} from 'playwright';
const origin='https://bidpicker-original-mobile-ui-production.up.railway.app/';
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
const page=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true,
 deviceScaleFactor:1,locale:'ko-KR',timezoneId:'Asia/Seoul'});
page.setDefaultTimeout(14000);
const queries=[],errors=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('request',req=>{const u=new URL(req.url());if(u.pathname==='/api/bidpicker/discover')queries.push({
  keyword:u.searchParams.get('keyword')||'',region:u.searchParams.get('region')||'전국',
  category:u.searchParams.get('category')||''})});
let result=null;
try{
 await page.goto(origin,{waitUntil:'domcontentloaded',timeout:35000});
 await page.waitForSelector('.bottom-item',{timeout:25000});
 const skip=page.locator('.onboard-top button');
 if(await skip.count())await skip.click();
 await page.locator('.bottom-item').nth(1).click();
 await page.waitForSelector('.quick-filters .chip');
 const completed=new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>reject(new Error('G2B_REGION_SEARCH_TIMEOUT')),205000);
  page.on('response',async r=>{
   try{
    const url=new URL(r.url());
    if(!/^\/api\/bidpicker\/live\/jobs\/[a-f0-9]{32}$/.test(url.pathname))return;
    const obj=await r.json();
    if(obj.status==='completed'||obj.status==='blocked'){
     clearTimeout(timer);resolve(obj);
    }
   }catch{}
  });
 });
 await page.locator('.quick-filters .chip').first().click();
 await page.waitForSelector('.popup .chip-flow');
 await page.locator('.popup .chip-flow .chip').filter({hasText:'서울'}).first().click();
 console.log('LIVE_UI_REGION_SELECTED','서울');
 result=await completed;
 console.log('LIVE_UI_REGION_RESULT',JSON.stringify({
  status:result.status,verified:result.live_search_verified,source:result.source,
  db_reads:result.db_reads,total:result.total,reason:result.reason,
  filters:result.appliedOfficialFilters,
  first:result.items?.slice(0,2).map(x=>({no:x.bidNo,title:x.title}))}));
 assert.ok(queries.some(x=>x.region==='서울'),'UI failed to send Seoul to official site');
 assert.equal(result.status,'completed','Official region search did not complete');
 assert.equal(result.live_search_verified,true,'Official region filter not verified');
 assert.equal(result.db_reads,0,'Region search must never query database');
 assert.equal(result.appliedOfficialFilters?.bidPbancNm,'서울',
   'Must search real G2B bid notice title rather than eligibility-only region');
 assert.equal(result.appliedOfficialFilters?.source_region_eligibility_code,null,
   'Do not mislabel 참가제한지역 as my locality');
 assert.equal(result.regionMatchBasis,'notice_title_or_agency_name',
   'Only geographically relevant verified records can be shown');
 assert.ok(result.total>0,'Known live 서울 notice search must NOT pass with zero results');
 assert.ok(result.items.every(b=>b.title.includes('서울')||b.agencyName.includes('서울')),
   'Returned notices must have actual 서울 name evidence');
 assert.equal(errors.length,0,'Mobile JS runtime errors');
 await page.waitForTimeout(300);
 assert.equal(await page.locator('.error-panel').count(),0,'UI incorrectly renders an error');
 const cards=page.locator('.cards-list .bid-card');
 assert.ok(await cards.count()>0,'Actual 서울 tender cards missing from mobile UI');
 console.log('LIVE_UI_REGION_VISIBLE',JSON.stringify({
   count:await cards.count(),titles:(await page.locator('.cards-list .bid-card h3').allTextContents()).slice(0,6)}));
 console.log('LIVE_UI_REGION_PASS',JSON.stringify({total:result.total,request:queries.at(-1)}));
 // A second ACTUAL mobile UI selection, no mocked G2B source:
 // tapping the IT category tile must show authentic notices, not page 0.
 await page.locator('.bottom-item').nth(0).click();
 await page.waitForSelector('.category-tile');
 const categoryCompleted=new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>reject(new Error('G2B_IT_CATEGORY_LIVE_TIMEOUT')),205000);
  const onResponse=async r=>{
   try{
    const u=new URL(r.url());
    if(!/^\/api\/bidpicker\/live\/jobs\/[a-f0-9]{32}$/.test(u.pathname))return;
    const value=await r.json();
    if(value.status==='completed'||value.status==='blocked'){
      page.off('response',onResponse);clearTimeout(timer);resolve(value);
    }
   }catch{}
  };
  page.on('response',onResponse);
 });
 await page.locator('.category-tile').first().click();
 const it=await categoryCompleted;
 console.log('LIVE_UI_IT_RESULT',JSON.stringify({
  status:it.status,verified:it.live_search_verified,total:it.total,
  query:queries.at(-1),reason:it.reason,filters:it.appliedOfficialFilters,
  first:it.items?.slice(0,3).map(x=>({no:x.bidNo,title:x.title}))}));
 assert.equal(queries.at(-1).category,'it','IT tile did not send category');
 assert.equal(queries.at(-1).region,'전국','Home IT tile retained stale Seoul region');
 assert.equal(it.status,'completed','Actual G2B IT category search did not complete');
 assert.equal(it.db_reads,0,'IT category fetched stale DB data');
 assert.ok(it.total>0,'IT category returned zero despite known public systems tenders');
 assert.equal(it.appliedOfficialFilters?.bidPbancNm,'시스템',
  'IT search must use verified real G2B bid title query, not guessed exact classification');
 await page.waitForTimeout(500);
 assert.ok(await page.locator('.cards-list .bid-card').count()>0,
  'Actual source IT tender cards missing from mobile screen');
 console.log('LIVE_UI_IT_PASS',JSON.stringify({total:it.total,
   visibleCards:await page.locator('.cards-list .bid-card').count()}));
}catch(e){
 console.error('LIVE_UI_REGION_FAILED',String(e));
 console.error('LIVE_UI_REGION_CONTEXT',JSON.stringify({queries,error:result?.reason,errors}));
 throw e;
}finally{
 await page.screenshot({path:'live-mobile-region.png',fullPage:true}).catch(()=>{});
 await browser.close();
}
