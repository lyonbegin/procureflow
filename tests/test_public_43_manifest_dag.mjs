import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const manifest=JSON.parse(readFileSync('n8n/operational_manifest.json','utf8'));
const wf=JSON.parse(readFileSync('n8n/strategy-workflows/A01-public-win-strategy.json','utf8'));
const blocks=manifest.blocks;
assert.equal(blocks.length,43);
assert.equal(wf.nodes.length,43);
assert.equal(wf.meta.simulation_only,true);
assert.equal(wf.meta.native_n8n_execution_verified,false);
assert.equal(wf.meta.graph_mode,'manifest_directed_acyclic_dependency_edges_not_linear_fixture_sequence');
const ids=new Set(blocks.map(b=>b.id));
const map=new Map(wf.nodes.map(n=>[n.name.split(' · ')[0],n]));
assert.equal(map.size,43);
const edges=[];
for(const [name,data] of Object.entries(wf.connections)){
  const from=name.split(' · ')[0];
  assert(ids.has(from),'unexpected '+name);
  for(const output of data.main||[])for(const dest of output){
    const to=dest.node.split(' · ')[0];
    assert(ids.has(to),'unexpected destination '+dest.node);
    edges.push([from,to]);
  }
}
const raw=blocks.flatMap(b=>b.to.filter(t=>ids.has(t)).map(t=>[b.id,t]));
function path(start,goal,es){const seen=new Set([start]),queue=[start];while(queue.length){const x=queue.shift();for(const [a,b] of es)if(a===x&&!seen.has(b)){if(b===goal)return true;seen.add(b);queue.push(b)}}return false}
for(const [a,b] of raw)assert(path(a,b,edges),'manifest dependency missing '+a+' -> '+b);
for(const [a,b] of edges)assert(raw.some(([x,y])=>a===x&&b===y),'non-manifest edge '+a+' -> '+b);
assert(edges.length>42,'the old 42-edge serial chain must be rejected');
const degree=Object.fromEntries([...ids].map(id=>[id,0]));
for(const [,b] of edges)degree[b]++;
const pending=[...ids].filter(id=>!degree[id]);
let seen=0;
while(pending.length){const id=pending.shift();seen++;for(const [a,b] of edges)if(a===id&&!--degree[b])pending.push(b)}
assert.equal(seen,43,'DAG must not contain cycles');
const outgoing=id=>edges.filter(([a])=>a===id).map(([,b])=>b);
const incoming=id=>edges.filter(([,b])=>b===id).map(([a])=>a);
assert.deepEqual(outgoing('H04').sort(),['H05','H06']);
assert.deepEqual(incoming('P06').sort(),['P03','P04','P05']);
assert(outgoing('N02').includes('N05'));
assert(outgoing('N02').includes('O01'));
assert(incoming('H11').includes('H09')&&incoming('H11').includes('H10'));
assert.equal(outgoing('O04').length,0);
console.log('A01_ORIGINAL_43_MANIFEST_DAG_TOPOLOGY_PASS',JSON.stringify({nodes:43,edges:edges.length,branches:blocks.filter(b=>outgoing(b.id).length>1).length,joins:blocks.filter(b=>incoming(b.id).length>1).length}));
