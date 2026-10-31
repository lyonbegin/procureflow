/**
 * Pure, offline safety boundary for S01–S10 official n8n Chrome fixtures.
 * No network access or n8n runtime is used by this module.
 * Production QA HTTP nodes are replaced with local Code assertions BEFORE import.
 */
import {createHash} from 'node:crypto';
// Review-pinned canonical fixture digests: protect the isolated n8n Code-node
// sandbox from indirect network access / dynamic evaluation that regex cannot
// reliably detect. Any intended S01-S10 edit MUST update these with review.
// SHA256(JSON.stringify(JSON.parse(original JSON file))) — stable for formatting-only edits.
const CANONICAL_SCENARIO_SHA256=Object.freeze({
  S01:'320a72d13d2ed7171e1ce2238a86b8b2f4dffdcf6b62e86d5c8abfdd94218aa2',
  S02:'743b36fb2fae7e5919d44138023f1b25d192bf80538d6070a61e18c0c923e45e',
  S03:'8cc8b0971755708f101f2ca4c0d0562abe0b9f6e687f49d4cbabffa6233257fe',
  S04:'c6de72eac7efc674f411f07a9ca36bc8561925ba6e445f956b4c2e99b5e24a6b',
  S05:'1a64180b123e50ed940ee97f7bbaed120bdbfae28740fa0b2c9cdcbc59a15082',
  S06:'ecb22c20900f970b87e6e3307cbe52cb6d84e643e0d01982c037987918334ae4',
  S07:'35db1773b816da272f90e3cea059ffe3c37ed85d0e24d7cbb52f1002c0493c1f',
  S08:'5d78b81a9b33683c7de14de780f0180c1b1481618d32003687524465aabbfb91',
  S09:'ef505042f258fffb98944bd9954ee435dc254626931a5ab7194d1e6883c9b780',
  S10:'4e4a51233a1e740e97ebdc562258a02ea5f9564a152ace3097750a3e6483e772',
});
const ALLOWED_TYPES=new Set([
  'n8n-nodes-base.manualTrigger','n8n-nodes-base.code','n8n-nodes-base.httpRequest'
]);
// Reject code that can reach arbitrary APIs or load dynamic modules in the
// disposable n8n process. A literal "quote_required" is not a require() call.
const SIDE_EFFECTFUL_CODE=/\b(?:fetch|import|require|eval|Function|WebSocket|XMLHttpRequest)\s*\(|\b(?:globalThis|process)\s*(?:\.|\[)|\$(?:http|request|helpers)\b/;
const assert=(condition,message)=>{if(!condition)throw Error(message);};

/**
 * Fail closed before launching Chrome, creating an owner or importing workflows.
 * Playwright's request context is not protected by page.route(), so a mistaken
 * production N8N_E2E_URL or a redirected API call must never reach the network.
 */
export function assertIsolatedN8nUrl(input){
  let parsed;
  try{parsed=new URL(input)}catch{throw Error('Isolated n8n URL must be a valid loopback HTTP origin');}
  assert(parsed.protocol==='http:','Isolated n8n URL must use local HTTP');
  // localhost can be remapped in /etc/hosts or DNS. All three Chrome
  // drivers CREATE n8n owners and workflows, so use numeric loopback only.
  assert(['127.0.0.1','[::1]'].includes(parsed.hostname),
    'Isolated n8n URL must target numeric loopback only');
  // These are the two fixed disposable Docker test listeners. A random
  // loopback port may point at an unrelated local service or owner database.
  assert(['5678','5681'].includes(parsed.port),
    'Isolated n8n URL must use an approved disposable test port');
  assert(parsed.pathname==='/'&&!parsed.search&&!parsed.hash&&!parsed.username&&!parsed.password,
    'Isolated n8n URL must be an origin without path, credentials or query');
  return parsed.origin;
}

export function makeSafeScenario(original,id){
  assert(/^S(?:0[1-9]|10)$/.test(id),'Invalid synthetic scenario ID');
  assert(original&&typeof original==='object'&&!Array.isArray(original),'Invalid scenario JSON');
  assert(original.active===false,id+': original fixture must remain inactive');
  const canonicalDigest=createHash('sha256').update(JSON.stringify(original)).digest('hex');
  assert(canonicalDigest===CANONICAL_SCENARIO_SHA256[id],
    id+': fixture integrity mismatch — executable graph changed without digest review');
  assert(Array.isArray(original.nodes)&&original.nodes.length>0,id+': missing native nodes');
  const fixture=structuredClone(original);
  const httpNodes=fixture.nodes.filter(n=>n.type==='n8n-nodes-base.httpRequest');
  assert(httpNodes.length===1,id+': exactly one original QA node required');
  const names=new Set(),nodeIds=new Set();
  for(const n of fixture.nodes){
    assert(n&&ALLOWED_TYPES.has(n.type),id+': unsupported node '+n?.type);
    assert(typeof n.id==='string'&&n.id&&!nodeIds.has(n.id),id+': invalid/duplicate node ID');
    assert(typeof n.name==='string'&&n.name&&!names.has(n.name),id+': invalid/duplicate node name');
    assert(!Object.hasOwn(n,'credentials'),id+': credentials prohibited in synthetic fixture');
    nodeIds.add(n.id);names.add(n.name);
    if(n.type==='n8n-nodes-base.httpRequest'){
      assert(n.parameters?.method==='POST'&&
        n.parameters.url==='https://procureflow-api-production.up.railway.app/api/n8n/scenarios/'+id+'/verify',
        id+': unapproved external HTTP source');
      // Replace the ONLY original production QA endpoint with a local,
      // deterministic assertion. No HTTP Request node survives this function.
      n.type='n8n-nodes-base.code';
      n.typeVersion=2;
      n.parameters={mode:'runOnceForAllItems',jsCode:
        "const v=$input.first().json;"+
        "if(v.scenario_id!=="+JSON.stringify(id)+"||v.case_id!=='DEMO_ONLY'||v.simulation_only!==true||v.bid_submitted!==false||v.verdict!==v.expected||v.passed!==true) throw new Error('Scenario mocked QA assertion failed');"+
        "return [{json:{...v,qa_local_only:true}}];"};
      n.notes='ISOLATED CHROME TEST ONLY — local QA assertion; not remote G2B verification';
    }else if(n.type==='n8n-nodes-base.code'){
      assert(typeof n.parameters?.jsCode==='string'&&
        !SIDE_EFFECTFUL_CODE.test(n.parameters.jsCode),
        id+': side-effectful or dynamic Code node '+n.name);
    }
  }
  assert(!fixture.nodes.some(n=>n.type==='n8n-nodes-base.httpRequest'),
    id+': HTTP node not fully disabled');
  delete fixture.id;
  delete fixture.active;
  delete fixture.staticData;
  delete fixture.meta;
  fixture.tags=[];
  fixture.name='[ISOLATED CHROME '+id+'] '+fixture.name;
  return fixture;
}


/**
 * Verify the REAL n8n execution response, not merely the number of synthetic
 * trace rows. Every flow/event, state patch, recipient and before/after value
 * must match the reviewed scenario plan. No live G2B/business completion claim.
 *
 * The caller must pass the actual /rest/executions/{id} result and runData.
 * Offline tests exercise only this verifier's failure modes.
 */
export function verifyNativeScenarioEvidence({payload,scenario,baseState,execution,runData,fixture,expectedExecutionId,expectedWorkflowId}) {
  const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
  assert(scenario&&/^S(?:0[1-9]|10)$/.test(scenario.id),'Invalid native scenario plan');
  assert(execution?.status==='success','Native n8n execution did not succeed');
  // The Chrome POST /run execution ID must be the ID returned by the saved
  // native GET /rest/executions/:id. Reject a result from another execution.
  if(expectedExecutionId!==undefined){
    assert(typeof expectedExecutionId==='string'&&expectedExecutionId.length>0&&
      String(execution.id)===expectedExecutionId,
      'Native scenario execution ID does not match the Chrome run');
  }
  // The GET /rest/executions/:id payload must belong to the exact workflow
  // the Chrome driver just saved. Matching run IDs and a plausible trace
  // alone must not accept an execution from another isolated workflow.
  if(expectedWorkflowId!==undefined){
    assert(typeof expectedWorkflowId==='string'&&expectedWorkflowId.length>0&&
      String(execution.workflowId)===expectedWorkflowId,
      'Native scenario workflow ID does not match the Chrome-saved workflow');
  }
  assert(payload?.scenario_id===scenario.id&&payload.case_id==='DEMO_ONLY',
    'Native scenario/case identity mismatch');
  assert(payload.expected===scenario.expected&&payload.verdict===scenario.expected,
    'Native scenario expected verdict mismatch');
  assert(payload.qa_local_only===true&&payload.passed===true&&
    payload.workflow_status==='SIMULATED_PASS'&&payload.simulation_only===true&&
    payload.bid_submitted===false&&payload.not_a_real_bid===true,
    'Native scenario isolation and no-bid assertions missing');
  assert(Array.isArray(scenario.steps)&&Array.isArray(payload.trace)&&
    payload.trace.length===scenario.steps.length,
    'Native scenario trace length mismatch');
  assert(Array.isArray(fixture?.nodes)&&fixture.nodes.length>0&&
    runData&&typeof runData==='object'&&!Array.isArray(runData),
    'Native scenario execution nodes missing');
  const expectedNodes=fixture.nodes.map(n=>n.name).sort();
  const actualNodes=Object.keys(runData).sort();
  assert(same(actualNodes,expectedNodes),
    'Native scenario did not execute exactly the reviewed workflow nodes');
  // A runData key alone is not evidence that a node actually ran. Require
  // exactly one successful native execution with a JSON output per node.
  const nativeOutput=new Map();
  for(const name of expectedNodes){
    const runs=runData[name];
    assert(Array.isArray(runs)&&runs.length===1&&!runs[0]?.error,
      'Native scenario missing or failed node execution: '+name);
    const items=runs[0]?.data?.main?.[0];
    assert(Array.isArray(items)&&items.length===1&&
      items[0]?.json&&typeof items[0].json==='object'&&!Array.isArray(items[0].json),
      'Native scenario missing node JSON output: '+name);
    nativeOutput.set(name,items[0].json);
  }
  assert(same(nativeOutput.get('전체 사건 기록 검증됨'),payload),
    'Native scenario final payload differs from saved n8n runData');
  const state=structuredClone(baseState);
  for(let i=0;i<scenario.steps.length;i++){
    const step=scenario.steps[i];
    const patch=step.patch||{};
    const before={},after={};
    for(const key of Object.keys(patch)){
      // Scenario steps may introduce a new state key; native Code uses
      // prior.state[key] ?? null for its before snapshot.
      before[key]=state[key]??null;
      after[key]=patch[key];
    }
    const expected={
      index:step.index,flow:step.flow,event:step.event,
      recipients:step.recipients,input:before,output:patch,
      after,simulation_only:true
    };
    assert(same(payload.trace[i],expected),
      'Native scenario trace mismatch at step '+(i+1));
    Object.assign(state,patch);
    // Each intermediate PF step must have emitted the exact trace prefix and
    // state transition. A forged final trace cannot hide an incorrect step.
    const prefix=String(i+1).padStart(2,'0')+' · ';
    const stageNodes=fixture.nodes.filter(n=>n.name.startsWith(prefix));
    assert(stageNodes.length===1,'Native scenario reviewed PF step node missing: '+prefix);
    const stage=nativeOutput.get(stageNodes[0].name);
    assert(stage?.scenario_id===scenario.id&&stage.case_id==='DEMO_ONLY'&&
      stage.simulation_only===true&&stage.bid_submitted===false&&
      stage.latest_event===step.event&&stage.active_flow===step.flow&&
      same(stage.latest_output,patch)&&same(stage.trace,payload.trace.slice(0,i+1))&&
      same(stage.state,state),
      'Native scenario PF step output differs from reviewed transition: '+prefix);
  }
  assert(same(payload.state,state),'Native scenario final state differs from reviewed patches');
  return {
    scenario:scenario.id,traceSteps:scenario.steps.length,
    executedNativeNodes:actualNodes.length,
    status:'VERIFIED_ISOLATED_SYNTHETIC_EXECUTION_ONLY'
  };
}
