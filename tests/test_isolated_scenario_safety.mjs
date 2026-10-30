import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {makeSafeScenario,assertIsolatedN8nUrl,verifyNativeScenarioEvidence} from '../.github/pan-e2e/scenario-safety.mjs';

const fixture=id=>JSON.parse(readFileSync('n8n/workflows/'+id+'.json','utf8'));
for(let i=1;i<=10;i++){
  const id='S'+String(i).padStart(2,'0');
  test(id+' original QA HTTP is replaced before official n8n test import',()=>{
    const original=fixture(id);
    const unchanged=JSON.stringify(original);
    const safe=makeSafeScenario(original,id);
    assert.equal(JSON.stringify(original),unchanged,'Do not mutate canonical workflow');
    assert.equal(original.active,false);
    assert.equal(safe.active,undefined);
    assert.equal(safe.nodes.length,original.nodes.length);
    assert.equal(safe.nodes.filter(n=>n.type==='n8n-nodes-base.httpRequest').length,0);
    assert.equal(safe.nodes.filter(n=>n.parameters?.jsCode?.includes('qa_local_only:true')).length,1);
    assert(safe.name.startsWith('[ISOLATED CHROME '+id+']'));
    assert(safe.nodes.every(n=>!Object.hasOwn(n,'credentials')));
  });
}
const attacks=[
  ['active fixture',j=>{j.active=true;}],
  ['missing active flag',j=>{delete j.active;}],
  ['foreign QA endpoint',j=>{j.nodes.find(n=>n.type==='n8n-nodes-base.httpRequest').parameters.url='https://example.test/verify';}],
  ['extra remote HTTP node',j=>{const n=structuredClone(j.nodes.find(n=>n.type==='n8n-nodes-base.httpRequest'));n.id='injected-http';n.name='Injected HTTP';j.nodes.push(n);}],
  ['HTTP GET instead of approved QA POST',j=>{j.nodes.find(n=>n.type==='n8n-nodes-base.httpRequest').parameters.method='GET';}],
  ['credentials on code node',j=>{j.nodes.find(n=>n.type==='n8n-nodes-base.code').credentials={api:{id:'secret'}};}],
  ['duplicate node name',j=>{j.nodes[1].name=j.nodes[0].name;}],
  ['duplicate node ID',j=>{j.nodes[1].id=j.nodes[0].id;}],
  ['unverified executable node',j=>{j.nodes[1].type='n8n-nodes-base.executeCommand';}],
  ['fetch call',j=>{j.nodes.find(n=>n.type==='n8n-nodes-base.code').parameters.jsCode='await fetch("https://example.test")';}],
  ['dynamic import',j=>{j.nodes.find(n=>n.type==='n8n-nodes-base.code').parameters.jsCode='await import("node:http")';}],
  ['require call',j=>{j.nodes.find(n=>n.type==='n8n-nodes-base.code').parameters.jsCode='require("node:fs")';}],
  ['process environment access',j=>{j.nodes.find(n=>n.type==='n8n-nodes-base.code').parameters.jsCode='return process.env';}],
  ['globalThis access',j=>{j.nodes.find(n=>n.type==='n8n-nodes-base.code').parameters.jsCode='globalThis["fetch"]("https://example.test")';}],
  ['n8n HTTP helper',j=>{j.nodes.find(n=>n.type==='n8n-nodes-base.code').parameters.jsCode='await $helpers.httpRequest({url:"https://example.test"})';}],
  ['eval execution',j=>{j.nodes.find(n=>n.type==='n8n-nodes-base.code').parameters.jsCode='eval("1+1")';}]
];
for(const [name,mutate] of attacks){
  test('fail closed: '+name,()=>{
    const j=fixture('S01');mutate(j);
    assert.throws(()=>makeSafeScenario(j,'S01'),/scenario|node|QA|HTTP|credential|inactive|source|Code|fixture|original|unsupported|duplicate|side-effectful/i);
  });
}
test('reject non-S01..S10 scenario IDs',()=>{
  assert.throws(()=>makeSafeScenario(fixture('S01'),'S11'),/Invalid synthetic scenario ID/);
});


test('all canonical fixtures remain accepted after JSON parse/stringify normalization',()=>{
  for(let i=1;i<=10;i++){
    const id='S'+String(i).padStart(2,'0');
    const original=fixture(id);
    assert.doesNotThrow(()=>makeSafeScenario(JSON.parse(JSON.stringify(original)),id));
  }
});

// A blacklist of words like fetch/import cannot prove Code nodes are offline.
// These indirect and graph-level mutations MUST fail at the canonical digest
// boundary before a disposable n8n instance ever imports the fixture.
const integrityAttacks=[
  ['indirect computed fetch',j=>{j.nodes.find(n=>n.type==='n8n-nodes-base.code').parameters.jsCode="const f=global['fe'+'tch']; return f('https://example.test')";}],
  ['constructor-based dynamic execution',j=>{j.nodes.find(n=>n.type==='n8n-nodes-base.code').parameters.jsCode="return [].filter.constructor('return 42')()";}],
  ['computed helper invocation',j=>{j.nodes.find(n=>n.type==='n8n-nodes-base.code').parameters.jsCode="return $helpers['http'+'Request']({url:'https://example.test'})";}],
  ['unreviewed Code logic modification',j=>{j.nodes.find(n=>n.type==='n8n-nodes-base.code').parameters.jsCode+='\\n// modified';}],
  ['injected manual trigger',j=>{const n=structuredClone(j.nodes[0]);n.id='extra-trigger';n.name='Extra Trigger';j.nodes.push(n);}],
  ['new bypass connection',j=>{j.connections[j.nodes[0].name].main[0][0].node=j.nodes.at(-1).name;}],
  ['workflow execution settings changed',j=>{j.settings.executionOrder='v0';}],
  ['untrusted pin data',j=>{j.pinData={injected:{json:{bid_submitted:true}}};}],
  ['new hidden workflow tag',j=>{j.tags=[{id:'injected'}];}],
  ['QA node type bypass',j=>{j.nodes.find(n=>n.type==='n8n-nodes-base.httpRequest').type='n8n-nodes-base.code';}],
];
for(const [name,mutate] of integrityAttacks){
  test('fail closed at pinned fixture digest: '+name,()=>{
    const j=fixture('S01');mutate(j);
    assert.throws(()=>makeSafeScenario(j,'S01'),/fixture integrity mismatch/);
  });
}

test('official Google Chrome scenario driver must use the same fail-closed transformer',()=>{
  const source=readFileSync('.github/pan-e2e/scenarios.mjs','utf8');
  assert.match(source,/import\s*\{makeSafeScenario\s*,\s*assertIsolatedN8nUrl\s*,\s*verifyNativeScenarioEvidence\}\s*from\s*['"]\.\/scenario-safety\.mjs['"]/);
  assert.match(source,/makeSafeScenario\(JSON\.parse\(await readFile\(/);
  assert.doesNotMatch(source,/function\s+makeSafe\s*\(/);
});

test('official Chrome S01-S10 target accepts only an isolated HTTP loopback origin',()=>{
  for(const url of ['http://127.0.0.1:5678','http://localhost:5678','http://[::1]:5678']){
    assert.equal(assertIsolatedN8nUrl(url),new URL(url).origin);
  }
  for(const url of [
    'https://procureflow-n8n-editor-gateway-production.up.railway.app',
    'http://procureflow-api-production.up.railway.app:5678',
    'http://example.com:5678',
    'https://127.0.0.1:5678',
    'http://0.0.0.0:5678',
    'http://127.0.0.1',
    'http://127.0.0.1:5678/rest/workflows',
    'http://127.0.0.1:5678?redirect=prod',
    'http://user:password@127.0.0.1:5678',
    'http://127.0.0.1:5678/#admin',
    'not-a-url',
  ])assert.throws(()=>assertIsolatedN8nUrl(url),/Isolated n8n URL/,url);
});

test('Chrome scenario driver guards origin before browser launch and prevents API redirects',()=>{
  const source=readFileSync('.github/pan-e2e/scenarios.mjs','utf8');
  assert.match(source,/const base=assertIsolatedN8nUrl\(process\.env\.N8N_E2E_URL/);
  assert.match(source,/method,timeout:25000,maxRedirects:0/);
  assert(source.indexOf('const base=assertIsolatedN8nUrl')<source.indexOf('await mkdir(out,'));
  assert(source.indexOf('const base=assertIsolatedN8nUrl')<source.indexOf('browser=await chromium.launch'));
});


// This fixture only tests the native evidence VERIFIER. It does not simulate
// a real Chrome session or assert that actual G2B business handlers ran.
const plan=JSON.parse(readFileSync('n8n/scenarios.json','utf8'));
function syntheticNativeEvidence(id){
  const scenario=plan.scenarios.find(s=>s.id===id);
  const fixtureSafe=makeSafeScenario(fixture(id),id);
  const state=structuredClone(plan.base_state);
  const trace=scenario.steps.map(step=>{
    const before={},after={};
    for(const [key,value] of Object.entries(step.patch||{})){
      before[key]=state[key]??null;
      after[key]=value;
    }
    Object.assign(state,step.patch||{});
    return {index:step.index,flow:step.flow,event:step.event,
      recipients:step.recipients,input:before,output:step.patch||{},
      after,simulation_only:true};
  });
  const payload={
    scenario_id:id,case_id:'DEMO_ONLY',expected:scenario.expected,
    verdict:scenario.expected,qa_local_only:true,passed:true,
    workflow_status:'SIMULATED_PASS',simulation_only:true,
    bid_submitted:false,not_a_real_bid:true,state,trace
  };
  const runData=Object.fromEntries(fixtureSafe.nodes.map(n=>[n.name,[{data:{main:[[{json:{}}]]}}]]));
  // Model native intermediate node outputs separately from the final payload.
  // A verifier which only checks runData keys must reject missing/forged stages.
  const replayState=structuredClone(plan.base_state);
  for(let i=0;i<scenario.steps.length;i++){
    const step=scenario.steps[i];
    Object.assign(replayState,step.patch||{});
    const prefix=String(i+1).padStart(2,'0')+' · ';
    const name=fixtureSafe.nodes.find(n=>n.name.startsWith(prefix))?.name;
    assert(name,'Missing canonical fixture PF step '+prefix);
    runData[name][0].data.main[0][0].json={
      scenario_id:id,case_id:'DEMO_ONLY',simulation_only:true,
      bid_submitted:false,latest_event:step.event,active_flow:step.flow,
      latest_output:structuredClone(step.patch||{}),
      trace:structuredClone(trace.slice(0,i+1)),
      state:structuredClone(replayState)
    };
  }
  runData['전체 사건 기록 검증됨'][0].data.main[0][0].json=structuredClone(payload);
  return {payload,scenario,baseState:plan.base_state,
    execution:{status:'success',id:'native-test-1'},expectedExecutionId:'native-test-1',
    runData,fixture:fixtureSafe};
}
for(let i=1;i<=10;i++){
  const id='S'+String(i).padStart(2,'0');
  test(id+' verifier accepts full synthetic trace and exact reviewed node set',()=>{
    const v=syntheticNativeEvidence(id);
    const result=verifyNativeScenarioEvidence(v);
    assert.equal(result.scenario,id);
    assert.equal(result.traceSteps,v.scenario.steps.length);
    assert.equal(result.executedNativeNodes,v.fixture.nodes.length);
    assert.equal(result.status,'VERIFIED_ISOLATED_SYNTHETIC_EXECUTION_ONLY');
  });
}
const nativeEvidenceAttacks=[
  ['wrong event',v=>{v.payload.trace[0].event='ForgedEvent';}],
  ['wrong flow',v=>{v.payload.trace[0].flow='PF15';}],
  ['wrong recipients',v=>{v.payload.trace[0].recipients=['PF15'];}],
  ['wrong step index',v=>{v.payload.trace[0].index=77;}],
  ['tampered patch',v=>{v.payload.trace[1].output={qualified:true};}],
  ['tampered before state',v=>{v.payload.trace[1].input={qualified:true};}],
  ['tampered after state',v=>{v.payload.trace[1].after={qualified:true};}],
  ['unreviewed trace field',v=>{v.payload.trace[0].bid_submitted=true;}],
  ['missing trace row',v=>{v.payload.trace.pop();}],
  ['extra trace row',v=>{v.payload.trace.push({...v.payload.trace[0]});}],
  ['wrong final state',v=>{v.payload.state.qualified=true;}],
  ['unexpected extra native node',v=>{v.runData['Injected Remote HTTP']=[{}];}],
  ['missing executed native node',v=>{delete v.runData[v.fixture.nodes[0].name];}],
  ['native execution failed',v=>{v.execution.status='error';}],
  ['fake native success without local QA',v=>{v.payload.qa_local_only=false;}],
  ['claimed actual bid submission',v=>{v.payload.bid_submitted=true;}],
  ['wrong scenario identity',v=>{v.payload.scenario_id='S10';}],
  ['wrong expected verdict',v=>{v.payload.verdict='READY_FOR_MANUAL_PARTICIPATION';}],
  ['not marked simulated',v=>{v.payload.simulation_only=false;}],
  ['missing no-real-bid marker',v=>{v.payload.not_a_real_bid=false;}],
  ['native execution ID mismatch',v=>{v.execution.id='another-run';}],
  ['native execution ID absent',v=>{delete v.execution.id;}],
  ['native node key without execution',v=>{v.runData[v.fixture.nodes[0].name]=[];}],
  ['native node failed execution',v=>{v.runData[v.fixture.nodes[0].name][0].error={message:'failed'};}],
  ['native node output missing',v=>{v.runData[v.fixture.nodes[0].name][0].data.main=[[]];}],
  ['native node duplicate executions',v=>{v.runData[v.fixture.nodes[0].name].push(structuredClone(v.runData[v.fixture.nodes[0].name][0]));}],
  ['final native output differs from claimed payload',v=>{v.runData['전체 사건 기록 검증됨'][0].data.main[0][0].json.verdict='FORGED';}],
  ['intermediate native state forged',v=>{const n=v.fixture.nodes.find(n=>n.name.startsWith('01 · ')).name;v.runData[n][0].data.main[0][0].json.state.qualified=true;}],
  ['intermediate native trace forged',v=>{const n=v.fixture.nodes.find(n=>n.name.startsWith('02 · ')).name;v.runData[n][0].data.main[0][0].json.trace[0].event='FAKE';}],
  ['intermediate native event forged',v=>{const n=v.fixture.nodes.find(n=>n.name.startsWith('01 · ')).name;v.runData[n][0].data.main[0][0].json.latest_event='FAKE';}],
];
for(const [name,attack] of nativeEvidenceAttacks){
  test('native execution evidence fail closed: '+name,()=>{
    const v=syntheticNativeEvidence('S02');
    attack(v);
    assert.throws(()=>verifyNativeScenarioEvidence(v),/Native scenario|Invalid native|Native n8n/);
  });
}
test('actual Chrome driver must call native evidence verifier before PASS',()=>{
  const source=readFileSync('.github/pan-e2e/scenarios.mjs','utf8');
  assert.match(source,/const nativeProof=verifyNativeScenarioEvidence\(\{/);
  assert(source.indexOf('verifyNativeScenarioEvidence({')<
    source.indexOf("report.push(row);"));
  assert.match(source,/nativeTraceVerified:true/);
});
