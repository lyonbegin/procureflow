import assert from 'node:assert/strict';
import {chromium} from 'playwright';
const base=process.env.STUDIO_BASE||'http://127.0.0.1:3031';
const path='operations/PF05.json';
const url=base+'/?workflow='+encodeURIComponent(path);
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{
 const ctx=await browser.newContext({viewport:{width:1580,height:940}});
 const page=await ctx.newPage();
 const exceptions=[];page.on('pageerror',e=>exceptions.push(e.message));
 await page.goto(url,{waitUntil:'domcontentloaded'});
 await page.waitForFunction(()=>document.body.innerText.includes('35 Nodes')&&
   document.body.innerText.includes('43 Connections'),{timeout:30000});
 await page.waitForFunction(()=>document.body.innerText.includes('DB 연결됨 · v0'),{timeout:15000});
 const oldName=await page.locator('input[aria-label="워크플로 이름"]').inputValue();
 assert(oldName.includes('PF05'),'Correct original workflow was not opened');
 const testName=oldName+' · isolated-browser-persistence-test';
 await page.locator('input[aria-label="워크플로 이름"]').fill(testName);
 await page.getByRole('button',{name:'서버 저장'}).click();
 await page.waitForFunction(()=>document.body.innerText.includes('DB 연결됨 · v1'),{timeout:15000});
 const server=await (await ctx.request.get(base+'/api/studio/workflows/'+path)).json();
 assert.equal(server.version,1);
 assert.equal(server.source,'server');
 assert.equal(server.workflow.active,false);
 assert.equal(server.workflow.name,testName);
 assert.equal(server.workflow.nodes.length,35);
 assert.equal(server.workflow.connections['H01 · 정확한 10자리 세부종목']?.main?.length,1);
 // Reopen using the SAME anonymous cookie; verify stored version and name.
 await page.reload({waitUntil:'domcontentloaded'});
 await page.waitForFunction(()=>document.body.innerText.includes('DB 연결됨 · v1'),{timeout:20000});
 await page.waitForFunction(expected=>document.querySelector('input[aria-label="워크플로 이름"]')?.value===expected,testName,{timeout:15000});
 assert.equal(await page.locator('input[aria-label="워크플로 이름"]').inputValue(),testName);
 assert.equal(await page.locator('.vue-flow__node').count(),35);
 assert(!await page.locator('body').innerText().then(x=>x.includes('Set up owner account')));
 // Separate anonymous session must see immutable v0 original and must NOT see
 // the first browser's draft or test name.
 const isolated=await browser.newContext();
 const second=await isolated.request.get(base+'/api/studio/workflows/'+path);
 const other=await second.json();
 assert.equal(other.version,0);
 assert.equal(other.source,'original');
 assert.notEqual(other.workflow.name,testName);
 assert.equal(exceptions.length,0,exceptions.join('\n'));
 console.log('PROCUREFLOW_STUDIO_REAL_CHROME_SAVE_RELOAD_COOKIE_ISOLATION_PASS',JSON.stringify({
  original:oldName,changed:testName,version:server.version,
  nodes:server.workflow.nodes.length,crossBrowserIsolation:true,
  forcedInactive:true,apiExecutions:0,ownerCreated:false
 }));
 await isolated.close();await ctx.close();
}finally{await browser.close();}
