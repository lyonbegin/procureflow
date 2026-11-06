import assert from 'node:assert/strict';
import {chromium} from 'playwright';

const origin='https://bidpicker-original-mobile-ui-production.up.railway.app/';
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
const page=await browser.newPage({
 viewport:{width:390,height:844},isMobile:true,hasTouch:true,
 deviceScaleFactor:1,locale:'ko-KR',timezoneId:'Asia/Seoul'});
page.setDefaultTimeout(12000);
const jsErrors=[],requests=[],apiResponses=[];
page.on('pageerror',e=>jsErrors.push(e.message));
page.on('request',r=>{
 const u=new URL(r.url());
 if(u.pathname.startsWith('/api/bidpicker/'))
  requests.push({path:u.pathname,keyword:u.searchParams.get('keyword'),region:u.searchParams.get('region')});
});
page.on('response',r=>{
 try{const u=new URL(r.url());if(u.pathname.startsWith('/api/bidpicker/'))
  apiResponses.push({path:u.pathname,status:r.status()});}catch{}
});
let captured={result:'not-started'};
try{
 await page.goto(origin,{waitUntil:'domcontentloaded',timeout:35000});
 await page.waitForSelector('.bottom-item',{timeout:25000});
 const skip=page.locator('.onboard-top button');
 if(await skip.count())await skip.click();
 console.log('LIVE_UI_HOME_OPEN',await page.title());
 await page.locator('.bottom-item').nth(1).click();
 await page.waitForSelector('.search-box input');
 await page.locator('.search-box input').fill('시스템');
 await page.locator('.search-submit').click();
 console.log('LIVE_UI_REAL_SEARCH_STARTED',JSON.stringify({keyword:'시스템',at:new Date().toISOString()}));
 await page.waitForFunction(
  ()=>!!document.querySelector('.cards-list .bid-card')||!!document.querySelector('.error-panel'),
  null,{timeout:205000,polling:500});
 const error=page.locator('.error-panel');
 if(await error.count()){
   const msg=(await error.innerText()).trim();
   captured={result:'failed',detail:msg,requests,apiResponses};
   throw new Error('REAL_MOBILE_UI_SEARCH_ERROR: '+msg);
 }
 const cards=page.locator('.cards-list .bid-card');
 const count=await cards.count();
 assert.ok(count>=1,'No actual G2B result cards');
 const names=(await page.locator('.cards-list .bid-card h3').allTextContents()).map(s=>s.trim());
 assert.ok(names.some(n=>n.includes('시스템')),'Tender titles do not match fresh G2B keyword');
 assert.ok(requests.some(q=>q.path==='/api/bidpicker/discover'&&q.keyword==='시스템'),
     'Mobile did not initiate new live official-site search');
 assert.ok(apiResponses.some(q=>q.path==='/api/bidpicker/discover'&&q.status===202),
     'New FastAPI live search was not queued with HTTP 202');
 assert.ok(apiResponses.some(q=>q.path.startsWith('/api/bidpicker/live/jobs/')&&q.status===200),
     'Mobile did not poll live G2B job');
 assert.equal(jsErrors.length,0,'Mobile browser JS errors');
 captured={result:'pass',count,titles:names.slice(0,8),requests:requests.slice(0,6),
   source:'g2b_live_official_site',apiResponses:apiResponses.slice(0,8),jsErrors};
 console.log('LIVE_UI_SEARCH_PASS',JSON.stringify(captured));
}catch(err){
 console.error('LIVE_UI_SEARCH_FAILED',String(err));
 console.error('LIVE_UI_API_EVIDENCE',JSON.stringify({requests:requests.slice(-12),apiResponses:apiResponses.slice(-12),jsErrors}));
 throw err;
}finally{
 await page.screenshot({path:'live-mobile-verification.png',type:'png',fullPage:true}).catch(()=>{});
 await browser.close();
}
