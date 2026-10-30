import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {makeSafeScenario} from '../.github/pan-e2e/scenario-safety.mjs';

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
  assert.match(source,/import\s*\{makeSafeScenario\}\s*from\s*['"]\.\/scenario-safety\.mjs['"]/);
  assert.match(source,/makeSafeScenario\(JSON\.parse\(await readFile\(/);
  assert.doesNotMatch(source,/function\s+makeSafe\s*\(/);
});
