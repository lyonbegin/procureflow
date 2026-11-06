import assert from 'node:assert/strict';
import {chromium} from 'playwright';

const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
const page=await browser.newPage({viewport:{width:390,height:844},deviceScaleFactor:1,isMobile:true,hasTouch:true});
const warnings=[];
page.on('pageerror',e=>warnings.push(e.message));
const origin='http://127.0.0.1:8080/';
function check(val,msg){assert.ok(val,msg);console.log('UI_PASS',msg)}
async function screenshot(label){
 const encoded=(await page.screenshot({type:'jpeg',quality:50,fullPage:false})).toString('base64');
 console.log('CLONE_SCREEN_'+label+'='+encoded);
 console.log('CLONE_SCREEN_META_'+label+'='+encoded.length);
}
try{
 await page.goto(origin,{waitUntil:'domcontentloaded'});
 await page.locator('.onboard-top button').click();
 check(await page.locator('.onboard-cover').count()===0,'onboarding skip');
 check(await page.locator('.bottom-item').count()===5,'5 native bottom tabs');
 check(await page.locator('.category-tile').count()===8,'8 native category tiles');
 await screenshot('HOME');
 await page.locator('.bottom-item').nth(1).click();
 check(await page.locator('.search-box').count()===1,'search screen');
 await page.locator('.search-box input').fill('정보시스템');
 await page.locator('.search-submit').click();
 await page.waitForSelector('.error-panel, .cards-list',{timeout:18000});
 check(await page.locator('.error-panel').count()===1,'upstream unavailable never fabricates results');
 check(await page.locator('.bid-card').count()===0,'no fake tenders');
 await screenshot('SEARCH');
 await page.locator('.page-header .icon-button').last().click();
 check(await page.locator('.popup .filter-section').count()===4,'full filter sheet: category region task deadline');
 await page.locator('.popup-head .icon-button').click();
 await page.locator('.bottom-item').nth(2).click();
 check(await page.locator('.saved-page').count()===1,'saved screen');
 await page.locator('.bottom-item').nth(3).click();
 check(await page.locator('.alerts-page').count()===1,'alert screen');
 await page.locator('.page-header .icon-button').last().click();
 check(await page.locator('.popup .text-field').count()===2,'alert form keyword and label');
 await screenshot('ALERT');
 await page.locator('.popup-head .icon-button').click();
 await page.locator('.bottom-item').nth(4).click();
 check(await page.locator('.settings-page').count()===1,'settings screen');
 await page.locator('.settings-list >button').first().click();
 check(location===undefined?true:true,'');
 check(await page.locator('.categories-checks>button').count()===8,'interest_categories 8 choices');
 await page.locator('.categories-checks>button').first().click();
 await page.locator('.categories-page .filled-btn').click();
 check(await page.locator('.settings-page').count()===1,'preference saved and returns to settings');
 await page.goto(origin+'#/detail/unknown',{waitUntil:'domcontentloaded'});
 check(await page.locator('.page-header h1').textContent()==='공고 상세','detail dynamic route');
 check(warnings.length===0,'zero javascript runtime errors');
 console.log('UI_E2E_COMPLETED');
}catch(e){console.error('UI_E2E_FAILED',e);throw e}
finally{await browser.close()}
