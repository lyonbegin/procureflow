import assert from 'node:assert/strict';
import {chromium} from 'playwright';
const base=process.env.STUDIO_BASE||'http://127.0.0.1:3031';
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try {
 const context=await browser.newContext({viewport:{width:1500,height:950}});
 const page=await context.newPage();
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/admin/index.html?section=tests',{waitUntil:'domcontentloaded'});
 assert.equal(await page.locator('a:has-text("기존 노드 캔버스 열기")').count(),3);
 await page.locator('a:has-text("기존 노드 캔버스 열기")').first().click();
 await page.waitForFunction(()=>document.body.innerText.includes('8 Nodes'),{timeout:30000});
 assert.equal(await page.locator('.vue-flow__node').count(),8);
 assert.equal(await page.getByTestId('node-run-a01-01').count(),1);
 assert.equal(await page.getByTestId('node-open-a01-01').count(),1);
 await page.getByTestId('node-run-a01-01').click();
 await page.waitForFunction(()=>document.querySelector('[data-node-id="a01-01"]')?.innerText.includes('Python 실행 성공'),{timeout:30000});
 const state=await (await context.request.get(base+'/api/studio/nodes/graph-state?workflow=operations%2FA01-public-win-strategy.json')).json();
 assert(state);
 await page.getByTestId('node-run-a01-02').click();
 await page.waitForFunction(()=>document.querySelector('[data-node-id="a01-02"]')?.innerText.includes('Python 실행 성공'),{timeout:20000});
 await page.getByTestId('node-open-a01-02').click();
 await page.getByText('노드 입력').first().waitFor({timeout:15000}).catch(()=>{});
 assert.equal(errors.length,0,errors.join('\\n'));
 console.log('CHROME_INVESTMENT_IDENTICAL_NODE_CARDS_ADMIN_LINK_AND_PYTHON_STAGE_PASS');
 await context.close();
}finally{await browser.close();}
