// Compile-time read-only candidate verification: never connects to n8n/DB.
import assert from 'node:assert/strict';
import {readFile,readdir,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {join} from 'node:path';
import {runInNewContext} from 'node:vm';
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
// The candidate's CUSTOM Business Operation sanitizes success output; it
// strips workflow_trace on purpose. Validate the POST-GRAFT PF05 graph using
// the *actual sanitized gate shape*, not the pre-augmentation Code output.
const pf05=JSON.parse(await readFile(join(dest,'operational','PF05.json'),'utf8'));
const byName=new Map(pf05.nodes.map(n=>[n.name,n]));
const name=id=>pf05.nodes.find(n=>n.name.startsWith(id+' · ')&&n.type==='n8n-nodes-base.code')?.name;
const h05=name('H05'),h06=name('H06'),h07=name('H07'),h02=name('H02'),h01=name('H01');
const checked=byName.get('검증 H07 · 분기 결과 합치기');
const merged=byName.get('합류 H07 · 모든 선행 분기');
assert(h01&&h02&&h05&&h06&&h07&&checked&&merged,'PF05 H07 candidate nodes missing');
assert.equal(merged.parameters.numberInputs,2);
for(const [id,port] of [['H05',0],['H06',1]]){
 const custom=id+' · Business Operation (공식 증빙 게이트)';
 assert(pf05.connections[custom].main[0].some(x=>x.node===merged.name&&x.index===port),
   id+' post-graft custom gate does not feed verified H07 port');
}
const run=(code,items,previous={})=>{
 const scope={$input:{all:()=>items.map(json=>({json})),first:()=>({json:items[0]})},
   $:(name)=>({first:()=>({json:previous[name]})})};
 return runInNewContext('(function(){'+code+'})()',scope,{timeout:1000})[0].json;
};
const gate=(id,caseId='R26BK01787028',status='VERIFIED')=>({
 operation_id:id,case_id:caseId,bid_no:caseId,flow_id:'PF05',inspection_status:status,
 evidence_verified:status==='VERIFIED',actual_job_executed:false
});
const upstream={flow_id:'PF05',case_id:'R26BK01787028',bid_no:'R26BK01787028',last_block:'H01',
 previous_block:{block_id:'H01',output:{validated_detail10:'8111159901'}},
 blocks:[{id:'H02',name:'10년 기간 분할',input:'validated_detail10+window',output_value:{windows:[]},features:[],next_blocks:['H03'],status:'partial'}],
 workflow_trace:[{block_id:'H01',output:{validated_detail10:'8111159901'}}]};
const h02node=byName.get(h02);
const restored=run(h02node.parameters.jsCode,[gate('H01')],{[h01]:upstream});
assert.equal(restored.last_block,'H02');
assert.equal(restored.workflow_trace.length,2);
assert.throws(()=>run(h02node.parameters.jsCode,[gate('H01',undefined,'HOLD')],{[h01]:upstream}),/PF05_UPSTREAM_GATE_NOT_VERIFIED_H02/);
const shared=[{block_id:'H02',output:{search_windows:[{id:'2016-2026'}]}},{block_id:'H04',output:{candidate_ids:['A']}}];
const mk=(id)=>({case_id:'R26BK01787028',bid_no:'R26BK01787028',flow_id:'PF05',last_block:id,
 previous_block:{block_id:id,output:id==='H05'?{opening_records:[{bid:'A'}]}:{award_records:[{award:'A'}]}},
 workflow_trace:[...shared,{block_id:id,output:id==='H05'?{opening_records:[{bid:'A'}]}:{award_records:[{award:'A'}]}}],
 blocks:[{id:'H07',name:'10년 개찰·낙찰 완전성',input:'opening+awards+windows',
 output_value:null,next_blocks:['H08'],features:[],status:'blocked'}]});
const originals={[h05]:mk('H05'),[h06]:mk('H06')};
const joined=run(checked.parameters.jsCode,[gate('H05'),gate('H06')],originals);
assert.equal(joined.dependency_join_complete,true);
assert.equal(joined.dependency_evidence_verified,false);
assert.equal(joined.dependency_inputs.H05.opening_records.length,1);
assert.equal(joined.dependency_inputs.H06.award_records.length,1);
const result=run(byName.get(h07).parameters.jsCode,[joined]);
assert.equal(result.last_block,'H07');
assert.equal(result.previous_block.input.upstream.search_windows.search_windows.length,1);
assert.equal(result.previous_block.input.upstream.opening_and_bidders.opening_records.length,1);
assert.equal(result.previous_block.input.upstream.awards.award_records.length,1);
assert.throws(()=>run(checked.parameters.jsCode,[gate('H05'),gate('H05')],originals),/H07_GATE_DUPLICATE_OR_UNKNOWN/);
assert.throws(()=>run(checked.parameters.jsCode,[gate('H05')],originals),/H07_GATE_MISSING_BRANCH/);
assert.throws(()=>run(checked.parameters.jsCode,[gate('H05'),gate('H06','R26BK00000001')],originals),/H07_GATE_NOT_VERIFIED/);
assert.throws(()=>run(checked.parameters.jsCode,[gate('H05'),gate('H06',undefined,'HOLD')],originals),/H07_GATE_NOT_VERIFIED/);
console.log('PF05_POST_CUSTOM_GATE_REAL_OUTPUT_JOIN_CONTRACT_PASS');

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
