import assert from 'node:assert/strict';
import {chromium} from 'playwright';
// The public operational management UI now uses NINE real G2B nodes.
// Existing B/C prototype canvases must remain compatible with the ORIGINAL
// investment shared-n8n-studio editor. No public 43-mock menu assumption.
const base=process.env.STUDIO_BASE||'http://127.0.0.1:3031';
const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
try{
 const context=await browser.newContext({viewport:{width:1440,height:930}});
 for(const [flow,expected] of [
  ['B01-private-software-proposal.json',7],
  ['C01-staffing-service-proposal.json',7]]){
  const page=await context.newPage();const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/?workflow='+encodeURIComponent('operations/'+flow),
      {waitUntil:'domcontentloaded'});
  await page.waitForFunction(n=>document.querySelectorAll('.vue-flow__node').length===n,
      expected,{timeout:30000});
  assert.equal(await page.locator('.vue-flow__node').count(),expected,flow);
  const record=await context.request.get(base+'/api/studio/workflows/operations/'+flow);
  assert.equal(record.status(),200);
  const body=await record.json();
  assert.equal(body.workflow.nodes.length,expected);
  assert.equal(errors.length,0,errors.join('\n'));
  await page.close();
 }
 console.log('ORIGINAL_SHARED_STUDIO_B_AND_C_7_NODES_CANVAS_REGRESSION_PASS');
 await context.close();
}finally{await browser.close();}
