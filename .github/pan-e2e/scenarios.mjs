#!/usr/bin/env node
/**
 * Issue #21 — safe Google Chrome execution of S01..S10 against isolated patched n8n.
 * All original HTTP Request nodes are replaced with a test-only local assertion:
 * no real API, G2B, Worker, credentials, or bid submission is contacted.
 * This verifies **native UI and execution**, NOT actual fault recovery/Worker semantics.
 */
import {chromium} from 'playwright';
import {parse as parseFlatted} from 'flatted';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import path from 'node:path';
import {makeSafeScenario,assertIsolatedN8nUrl,verifyNativeScenarioEvidence} from './scenario-safety.mjs';
const base=assertIsolatedN8nUrl(process.env.N8N_E2E_URL||'http://127.0.0.1:5678');
const out=process.env.N8N_SCENARIO_ARTIFACTS||'shared-pan-e2e-artifacts/scenarios';
const email='pan-test@example.invalid', password='PanSmokeStrong123!';
const report=[];
await mkdir(out,{recursive:true});
let browser, context, page;
const assert=(x,msg)=>{if(!x)throw Error(msg);};
async function api(method,endpoint,data) {
  const res=await context.request.fetch(base+endpoint,{
    method,timeout:25000,maxRedirects:0,
    ...(data===undefined?{}:{data,headers:{'content-type':'application/json'}})
  });
  const raw=await res.text();
  let body;
  try{body=JSON.parse(raw)}catch{body={raw:raw.slice(0,400)}}
  if(!res.ok())throw Error(method+' '+endpoint+' HTTP '+res.status()+' '+JSON.stringify(body).slice(0,500));
  return body;
}
async function eventually(label,cb,timeout=100000) {
  const started=Date.now();let latest;
  while(Date.now()-started<timeout){
    try{const result=await cb();if(result)return result;}catch(e){latest=e.message;}
    await new Promise(resolve=>setTimeout(resolve,650));
  }
  throw Error(label+' timeout: '+(latest||'no matching result'));
}
async function savedExecution(id) {
  const exec=(await api('GET','/rest/executions/'+id)).data;
  const data=typeof exec?.data==='string'?parseFlatted(exec.data):exec?.data;
  return {exec, runData:data?.resultData?.runData||{}};
}

try{
  browser=await chromium.launch({channel:'chrome',headless:true,args:['--no-sandbox']});
  context=await browser.newContext({viewport:{width:1440,height:900}});
  page=await context.newPage();
  await context.tracing.start({screenshots:true,snapshots:true,sources:true});
  await page.route('**/*',async route=>{
    const u=new URL(route.request().url());
    if(u.origin!==new URL(base).origin){await route.abort();return;}
    await route.continue();
  });
  const settings=(await api('GET','/rest/settings')).data;
  if(settings?.userManagement?.showSetupOnFirstLoad)
    await api('POST','/rest/owner/setup',{email,firstName:'Pan',lastName:'Test',password});
  await api('POST','/rest/login',{emailOrLdapLoginId:email,password});
  const plan=JSON.parse(await readFile('n8n/scenarios.json','utf8'));
  assert(plan.origin==='fictional_test_fixtures','not an isolated scenario fixture');
  for(let i=1;i<=10;i++){
    const id='S'+String(i).padStart(2,'0');
    const item=plan.scenarios.find(x=>x.id===id);
    assert(item && item.expected,'missing expected test state '+id);
    try{
      const fixture=makeSafeScenario(JSON.parse(await readFile('n8n/workflows/'+id+'.json','utf8')),id);
      const saved=(await api('POST','/rest/workflows',fixture)).data;
      assert(saved?.id,'n8n did not persist '+id);
      await page.goto(base+'/workflow/'+saved.id,{waitUntil:'domcontentloaded'});
      await page.locator('[data-test-id="canvas"]').waitFor({timeout:35000});
      const executionResponse=page.waitForResponse(r=>
        r.url().includes('/rest/workflows/')&&r.url().includes('/run')&&r.request().method()==='POST',
        {timeout:35000});
      await page.locator('[data-test-id="execute-workflow-button"]').first().click({timeout:25000});
      const start=(await (await executionResponse).json()).data;
      const executionId=String(start?.executionId||start?.id||'');
      assert(executionId,id+': missing native execution ID');
      const result=await eventually(id+' native result',async()=>{
        const {exec,runData}=await savedExecution(executionId);
        const node=runData['전체 사건 기록 검증됨']?.at(-1);
        const payload=node?.data?.main?.[0]?.[0]?.json;
        if(!payload){if(exec.status==='error')throw Error(id+': execution failed');return null;}
        return {exec,runData,payload};
      },100000);
      assert(result.payload.qa_local_only===true,id+': not isolated');
      assert(result.payload.workflow_status==='SIMULATED_PASS',id+': unexpected simulation status');
      assert(result.payload.verdict===item.expected,id+': expected '+item.expected+' got '+result.payload.verdict);
      assert(result.payload.trace?.length===item.steps.length,id+': trace length mismatch');
      assert(result.payload.simulation_only===true && result.payload.bid_submitted===false,id+': unsafe result');
      // Bind the PASS verdict to actual native n8n runData and the complete
      // reviewed scenario plan, not merely a trace length or claimed verdict.
      const nativeProof=verifyNativeScenarioEvidence({
        payload:result.payload,scenario:item,baseState:plan.base_state,
        execution:result.exec,runData:result.runData,fixture,
        expectedExecutionId:executionId
      });
      await page.screenshot({path:path.join(out,id+'-executed.png'),fullPage:true});
      const row={scenario:id,verdict:'PASS',expected:item.expected,workflowId:saved.id,executionId,runNodes:Object.keys(result.runData).length,traceSteps:item.steps.length,nativeTraceVerified:true,executedNativeNodes:nativeProof.executedNativeNodes,source:'isolated_n8n_browser_synthetic_only'};
      report.push(row);
      console.log('CHROME_SCENARIO_PASS',JSON.stringify(row));
    }catch(e) {
      report.push({scenario:id,verdict:'FAIL',error:e?.message||String(e)});
      console.error('CHROME_SCENARIO_FAIL',id,e);
      await page.screenshot({path:path.join(out,id+'-failure.png'),fullPage:true}).catch(()=>{});
    }finally {
      await writeFile(path.join(out,'results.json'),JSON.stringify(report,null,2)+'\n');
    }
  }
  assert(report.length===10&&report.every(x=>x.verdict==='PASS'),'Only '+report.filter(x=>x.verdict==='PASS').length+'/10 scenarios passed');
  console.log('CHROME_ALL_TEN_SCENARIOS_PASS');
}catch(e){console.error('CHROME_SCENARIO_SUITE_FAILED',e);process.exitCode=1;}
finally{
  if(context)await context.tracing.stop({path:path.join(out,'trace.zip')}).catch(()=>{});
  if(context)await context.close().catch(()=>{});
  if(browser)await browser.close().catch(()=>{});
}
