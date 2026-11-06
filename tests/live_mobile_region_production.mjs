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
 assert.equal(result.appliedOfficialFilters?.region_restriction,'서울특별시');
 assert.ok(result.appliedOfficialFilters?.region_code_from_g2b_selector,
   'Official region code missing in source POST');
 assert.equal(errors.length,0,'Mobile JS runtime errors');
 await page.waitForTimeout(300);
 assert.equal(await page.locator('.error-panel').count(),0,'UI incorrectly renders error for zero verified results');
 console.log('LIVE_UI_REGION_PASS',JSON.stringify({total:result.total,request:queries.at(-1)}));
}catch(e){
 console.error('LIVE_UI_REGION_FAILED',String(e));
 console.error('LIVE_UI_REGION_CONTEXT',JSON.stringify({queries,error:result?.reason,errors}));
 throw e;
}finally{
 await page.screenshot({path:'live-mobile-region.png',fullPage:true}).catch(()=>{});
 await browser.close();
}
