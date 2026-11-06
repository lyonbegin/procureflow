import assert from 'node:assert/strict';
import {chromium} from 'playwright';
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const page=await browser.newPage({viewport:{width:390,height:844},deviceScaleFactor:1,isMobile:true,hasTouch:true});
const errors=[],requested=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('request',r=>{if(r.url().includes('/api/bidpicker/discover'))requested.push(r.url())});
const origin='http://127.0.0.1:8080/';
const oldSource='https://www.pickersoft.com';
function check(cond,msg){assert.ok(cond,msg);console.log('UI_PASS',msg)}
const mock=[
 {id:'R26BM01032422-000',bidNo:'R26BM01032422',bidSeq:'000',
  title:'2027년~2028년 세종시 도서관 ICT 통합정보시스템 유지관리 용역',
  agencyName:'조달청',region:'',status:'',deadlineAt:null,budgetAmount:null,
  source:'fresh_g2b_official_site',regionBasis:'unverified'},
 {id:'R26BM01032671-000',bidNo:'R26BM01032671',bidSeq:'000',
  title:'우장산역 노후 에스컬레이터 교체공사',
  agencyName:'서울교통공사',region:'서울',status:'',deadlineAt:null,budgetAmount:null,
  source:'fresh_g2b_official_site',regionBasis:'agency_name_only'}
];
await page.route('**/api/bidpicker/discover?**',async route=>{
 const q=new URL(route.request().url()).searchParams;
 const kw=q.get('keyword')||'';
 const reg=q.get('region')||'전국';
 const items=mock.filter(x=>(!kw||x.title.includes(kw)||x.agencyName.includes(kw))&&(reg==='전국'||x.region===reg));
 await route.fulfill({status:200,contentType:'application/json',
   body:JSON.stringify({items,total:items.length,page:1,size:10,hasMore:false,source:'fresh_g2b_official_site',
   filterNotes:['지역은 발주기관 이름 기준입니다. 실제 입찰 참가 가능 지역과 다를 수 있습니다.']})});
});
await page.route('**/api/bidpicker/status',route=>route.fulfill({status:200,contentType:'application/json',
 body:JSON.stringify({status:'ok',new_db_notices:22,official_site_search_live_proven:true})}));
await page.route('**/api/bidpicker/detail/**',route=>route.fulfill({status:200,contentType:'application/json',
 body:JSON.stringify({source:'fresh_g2b_official_site',item:mock[0],attachments:[]})}));
try{
 await page.goto(origin,{waitUntil:'domcontentloaded'});
 await page.locator('.onboard-top button').click();
 check(await page.locator('.onboard-cover').count()===0,'onboarding skips');
 check(await page.locator('.bottom-item').count()===5,'original 5 bottom tabs retained');
 check(await page.locator('.category-tile').count()===8,'original 8 category tiles retained');
 await page.locator('.bottom-item').nth(1).click();
 await page.waitForSelector('.search-box');
 await page.locator('.search-box input').fill('정보시스템');
 await page.locator('.search-submit').click();
 await page.waitForSelector('.cards-list .bid-card',{timeout:12000});
 check((await page.locator('.bid-card h3').first().textContent()).includes('통합정보시스템'),'keyword search displays official-source notice');
 check(requested.some(x=>new URL(x).searchParams.get('keyword')==='정보시스템'),'keyword actually sent to backend');
 check((await page.locator('.bid-card .status-chip').first().textContent()).includes('상태 확인중'),'unknown status never fabricated OPEN');
 await page.locator('.search-box input').fill('');
 await page.locator('.search-submit').click();
 await page.waitForFunction(()=>document.querySelectorAll('.bid-card').length===2,{timeout:12000});
 await page.locator('.quick-filters .chip').first().click();
 await page.waitForSelector('.popup .chip-flow');
 await page.locator('.popup .chip-flow .chip').filter({hasText:'서울'}).first().click();
 await page.waitForFunction(()=>document.querySelectorAll('.bid-card').length===1,{timeout:12000});
 check(requested.some(x=>new URL(x).searchParams.get('region')==='서울'),'Seoul selection triggers our FastAPI URL with region param');
 check((await page.locator('.bid-card h3').first().textContent()).includes('우장산역'),'Seoul selection renders matching agency-region record');
 await page.locator('.page-header .icon-button').last().click();
 await page.waitForSelector('.popup .filter-section');
 check(await page.locator('.popup .filter-section').count()===4,'filter sheet retains category, region, task and deadline');
 await page.locator('.popup-head .icon-button').click();
 await page.locator('.bottom-item').nth(2).click();
 await page.waitForSelector('.saved-page');
 await page.locator('.bottom-item').nth(3).click();
 await page.waitForSelector('.alerts-page');
 await page.locator('.page-header .icon-button').last().click();
 await page.waitForSelector('.popup .text-field');
 check(await page.locator('.popup .text-field').count()===2,'alert condition form retained');
 await page.locator('.popup-head .icon-button').click();
 await page.locator('.bottom-item').nth(4).click();
 await page.waitForSelector('.settings-page');
 check((await page.locator('body').innerText()).includes('설정'),'settings retained');
 check(requested.every(x=>!x.startsWith(oldSource)),'never uses original third-party API');
 check(errors.length===0,'no JavaScript runtime errors');
 console.log('UI_E2E_COMPLETED');
}catch(e){console.error('UI_E2E_FAILED',e);throw e}
finally{await browser.close()}
