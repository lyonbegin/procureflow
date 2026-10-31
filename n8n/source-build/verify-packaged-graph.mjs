// Compile-time read-only candidate verification: never connects to n8n/DB.
import assert from 'node:assert/strict';
import {readFile,readdir,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {join} from 'node:path';
const src=process.env.PF_SOURCE||'/home/node';
const dest=process.env.PF_OUTPUT||'/home/node/compiled-native';
const manifest=JSON.parse(await readFile(join(src,'procureflow-operational-manifest.json'),'utf8'));
assert.equal(manifest.engine,'n8n_only');
assert.equal(manifest.flows.length,15);
assert.equal(manifest.blocks.length,43);
const pfs=Array.from({length:16},(_,i)=>'PF'+String(i).padStart(2,'0'));
const sims=Array.from({length:10},(_,i)=>'S'+String(i+1).padStart(2,'0'));
assert.deepEqual((await readdir(join(dest,'operational'))).filter(s=>/^PF(?:0[0-9]|1[0-5])\.json$/.test(s)).sort(),pfs.map(s=>s+'.json'));
assert.deepEqual((await readdir(join(src,'procureflow-demo-workflows'))).filter(s=>/^S(?:0[1-9]|10)\.json$/.test(s)).sort(),sims.map(s=>s+'.json'));
const ids=new Set(),ops=new Set(),hashes=[],workflows=[];
for(const id of [...pfs,...sims]){
  const file=id.startsWith('PF')?join(dest,'operational',id+'.json'):join(src,'procureflow-demo-workflows',id+'.json');
  const raw=await readFile(file,'utf8'),wf=JSON.parse(raw);
  assert.equal(wf.active,false,id+' workflow must be inactive');
  assert(!ids.has(wf.id),'duplicate workflow ID: '+id);
  ids.add(wf.id);
  assert(wf.nodes.length>0,id+' empty graph');
  const nodes=wf.nodes.filter(n=>n.type==='CUSTOM.procureFlowBusinessOperation');
  if(id.startsWith('PF')){
    const owner=manifest.flows.find(x=>x.id===id);
    const expected=owner?.owned_blocks||[];
    assert.equal(nodes.length,expected.length,id+' custom operation count');
    assert.deepEqual(nodes.map(x=>x.parameters.operationId).sort(),[...expected].sort(),id+' wrong operation IDs');
    for(const node of nodes){
      assert.equal(node.parameters.evidenceHandling,'hold');
      assert.equal(node.parameters.bidNo,'R26BK01787028');
      const ports=wf.connections?.[node.name]?.main;
      assert.equal(ports?.length,2,'missing 2 native ports: '+id);
      assert(ports[1]?.length>0,'missing HOLD successor: '+id);
      assert(!ops.has(node.parameters.operationId),'duplicate operationId');
      ops.add(node.parameters.operationId);
    }
  }else assert.equal(nodes.length,0,'synthetic scenario contains production Business Operation');
  hashes.push(createHash('sha256').update(raw).digest('hex'));
  workflows.push({id,workflowId:wf.id,nodeCount:wf.nodes.length});
}
assert.equal(ids.size,26);
assert.equal(ops.size,43);
assert.deepEqual([...ops].sort(),manifest.blocks.map(b=>b.id).sort());
const report={
  schema:'procureflow.existing-n8n-image.candidate-parity.v1',
  workflows:26,pf:16,scenarios:10,nativeBusinessOperationNodes:43,
  databaseImported:false,ownerCreated:false,workflowExecuted:false,
  contentSha256:createHash('sha256').update(hashes.join('\n')).digest('hex'),
  files:workflows
};
await writeFile(join(dest,'package-audit.json'),JSON.stringify(report,null,2)+'\n');
console.log('EXISTING_N8N_26_43_IMAGE_PACKAGE_PASS',JSON.stringify({
  workflows:26,nativeGates:43,dbWrites:0,ownerWrites:0,digest:report.contentSha256
}));
