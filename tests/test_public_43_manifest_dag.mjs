import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const manifest=JSON.parse(readFileSync('n8n/operational_manifest.json','utf8'));
const wf=JSON.parse(readFileSync('n8n/strategy-workflows/A01-public-win-strategy.json','utf8'));
const ids=new Set(manifest.blocks.map(b=>b.id));
const business=wf.nodes.filter(n=>/^public-(N|H|Q|S|P|R|O)\d{2}$/.test(n.id));
const nodeByName=new Map(wf.nodes.map(n=>[n.name,n]));
const nameOf=new Map(business.map(n=>[n.id.slice(7),n.name]));
assert.equal(manifest.blocks.length,43);
assert.equal(business.length,43,'43 original business blocks must remain');
assert.equal(wf.nodes.length,45,'43 business + 2 native technical join nodes');
assert.equal(wf.meta.business_contracts,104);
assert.equal(wf.meta.simulation_only,true);
assert.equal(wf.meta.native_n8n_execution_verified,false);
assert.equal(wf.meta.graph_mode,'manifest_directed_acyclic_dependency_edges_not_linear_fixture_sequence');
assert.equal(nodeByName.size,wf.nodes.length);
const edges=[];
for(const [from,ports] of Object.entries(wf.connections)){
 assert(nodeByName.has(from),'unknown outgoing '+from);
 for(const output of ports.main||[])for(const to of output){
  assert(nodeByName.has(to.node),'unknown target '+to.node);
  edges.push({from,to:to.node,index:to.index});
 }
}
assert.equal(edges.length,54,'must be 52 business dependency edges plus two join hops');
const runPaths=new Map([...nodeByName.keys()].map(name=>[name,edges.filter(e=>e.from===name).map(e=>e.to)]));
function reachable(from,to) {
 const queue=[from],seen=new Set([from]);
 while(queue.length)for(const dst of runPaths.get(queue.shift())||[]){
  if(dst===to)return true;
  if(!seen.has(dst)){seen.add(dst);queue.push(dst)}
 }
 return false;
}
const raw=manifest.blocks.flatMap(b=>(b.to||[]).filter(x=>ids.has(x)).map(x=>[b.id,x]));
for(const [u,v] of raw)assert(reachable(nameOf.get(u),nameOf.get(v)),'manifest path missing '+u+' -> '+v);
const reducedLinks=[];
for(const [bid,name] of nameOf) {
 const todo=[...(runPaths.get(name)||[])],seen=new Set();
 while(todo.length){
  const next=todo.shift();
  if(seen.has(next))continue;
  seen.add(next);
  const n=nodeByName.get(next);
  if(business.some(b=>b.name===next)){reducedLinks.push([bid,n.id.slice(7)]);continue}
  todo.push(...(runPaths.get(next)||[]));
 }
}
for(const [u,v] of reducedLinks)assert(raw.some(([a,b])=>a===u&&b===v),'unapproved business edge '+u+' -> '+v);
const merge=wf.nodes.find(n=>n.id==='public-H07-native-merge');
const check=wf.nodes.find(n=>n.id==='public-H07-input-gate');
assert(merge&&check,'H07 merge/gate are required');
assert.equal(merge.type,'n8n-nodes-base.merge');
assert.equal(merge.parameters.numberInputs,2);
assert(edges.some(e=>e.from===nameOf.get('H05')&&e.to===merge.name&&e.index===0));
assert(edges.some(e=>e.from===nameOf.get('H06')&&e.to===merge.name&&e.index===1));
assert(edges.some(e=>e.from===merge.name&&e.to===check.name));
assert(edges.some(e=>e.from===check.name&&e.to===nameOf.get('H07')));
const degree=Object.fromEntries([...nodeByName.keys()].map(id=>[id,0]));
for(const {to} of edges)degree[to]++;
const pending=Object.keys(degree).filter(k=>!degree[k]);
let seen=0;
while(pending.length){const id=pending.shift();seen++;for(const {to} of edges.filter(e=>e.from===id))if(--degree[to]===0)pending.push(to)}
assert.equal(seen,45,'workflow must not have a dependency cycle');
function run(items){return runInNewContext(
 '(function(){'+check.parameters.jsCode+'})()',
 {$input:{all:()=>items.map(json=>({json}))}},
 {timeout:1000})[0].json}
const pre=[{block_id:'H02',output:{search_windows:[{from:'2016-10-24',to:'2026-10-22'}]}}];
const input=(id,bid='R26BK01787028')=>({
 flow_id:'PF05',case_id:bid,bid_no:bid,last_block:id,previous_block:{block_id:id},
 workflow_trace:[...pre,{block_id:id,output:id==='H05'?{opening_records:[{id:1}]}:{award_records:[{id:1}]}}]
});
const good=run([input('H05'),input('H06')]);
assert.equal(good.dependency_join_complete,true);
assert.equal(good.dependency_evidence_verified,false);
assert.equal(good.actual_job_executed,false);
assert.equal(good.dependency_inputs.H05.opening_records.length,1);
assert.equal(good.dependency_inputs.H06.award_records.length,1);
for(const [items,label] of [
 [[input('H05')],'missing'],
 [[input('H05'),input('H05')],'duplicate'],
 [[input('H05'),input('H06','R26BK00000001')],'cross case']
]){
 assert.throws(()=>run(items),undefined,label);
}
console.log('A01_43_BUSINESS_PLUS_2_NATIVE_H07_JOIN_PASS',JSON.stringify({business:43,technical:2,edges:54}));
