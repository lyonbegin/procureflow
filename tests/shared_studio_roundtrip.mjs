// Verify that the shared Studio does not lose original n8n semantics on import/export.
// Run with: node tests/shared_studio_roundtrip.mjs <shared-studio-root> <workflow-root>
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const [sharedRoot,workflowRoot]=process.argv.slice(2);
assert(sharedRoot&&workflowRoot,'Provide shared-studio root and packaged workflow root');
const {fromN8nWorkflow,toN8nWorkflow}=await import(pathToFileURL(path.resolve(sharedRoot,'playground/src/investment-adapter.js')).href);
const names=[
 ...Array.from({length:16},(_,i)=>`operations/PF${String(i).padStart(2,'0')}.json`),
 ...Array.from({length:10},(_,i)=>`scenarios/S${String(i+1).padStart(2,'0')}.json`)
];
function links(w){
 const result=[];
 for(const [source,types] of Object.entries(w.connections||{}))
  for(const [type,ports] of Object.entries(types||{}))
   for(let output=0;output<ports.length;output++)
    for(const target of ports[output]||[])
     result.push(JSON.stringify([source,type,output,target.node,target.type,target.index]));
 return result.sort();
}
let count=0,connections=0;
for(const name of names){
 const original=JSON.parse(await readFile(path.resolve(workflowRoot,name),'utf8'));
 const imported=fromN8nWorkflow(original);
 const exported=toN8nWorkflow({ ...imported });
 assert.equal(exported.active,false,`${name}: execution must be disabled`);
 assert.equal(exported.nodes.length,original.nodes.length,`${name}: node count`);
 const left=new Map(original.nodes.map(n=>[n.id,n]));
 for(const node of exported.nodes){
  const previous=left.get(node.id);
  assert(previous,`${name}: node id lost`);
  for(const field of ['type','typeVersion','name','parameters','credentials','continueOnFail','retryOnFail','notes','notesInFlow','webhookId'])
   if(Object.hasOwn(previous,field))assert.deepEqual(node[field],previous[field],`${name} / ${node.id}: ${field}`);
  assert.deepEqual(node.position,previous.position,`${name} / ${node.id}: position`);
 }
 assert.deepEqual(links(exported),links(original),`${name}: connection types, indexes or order lost`);
 count+=original.nodes.length;connections+=links(original).length;
 console.log('PASS',name,'nodes',original.nodes.length,'links',links(original).length);
}
console.log('ROUNDTRIP_PASS',names.length,'workflows',count,'nodes',connections,'links');
