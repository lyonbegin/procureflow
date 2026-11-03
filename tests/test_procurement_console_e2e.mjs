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
 await page.locator('[data-page="features"]').first().click();
 await page.waitForFunction(()=>document.querySelectorAll('#content tbody tr').length>=104,{timeout:20000});
 assert.equal(await page.locator('#content tbody tr').count(),111); // seven phase rows plus 104 original feature rows
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
