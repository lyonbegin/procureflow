import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'pf-native-business-node-'));
fs.copyFileSync('n8n/custom-nodes/ProcureFlowBusinessOperation.node.js',path.join(dir,'ProcureFlowBusinessOperation.node.js'));
fs.copyFileSync('n8n/operational_manifest.json',path.join(dir,'operational_manifest.json'));
const node=createRequire(import.meta.url)(path.join(dir,'ProcureFlowBusinessOperation.node.js'));
const {ProcureFlowBusinessOperation,safeApiBase,validateProvenance}=node;
const original={
  PROCUREFLOW_BUSINESS_READONLY_ENABLED:process.env.PROCUREFLOW_BUSINESS_READONLY_ENABLED,
  PROCUREFLOW_OPERATION_API_BASE:process.env.PROCUREFLOW_OPERATION_API_BASE,
  PROCUREFLOW_OPERATION_TEST_MODE:process.env.PROCUREFLOW_OPERATION_TEST_MODE
};
function configure(){
  process.env.PROCUREFLOW_BUSINESS_READONLY_ENABLED='1';
  process.env.PROCUREFLOW_OPERATION_API_BASE='http://127.0.0.1:58491';
  process.env.PROCUREFLOW_OPERATION_TEST_MODE='1';
}
const getParam=(v,i)=>({operationId:'N01',bidNo:'R26BK01787028',evidenceHandling:'hold'})[v];
const blocked={
  flow_id:'PF01',case_id:'R26BK01787028',read_only:true,
  simulation_only:false,actual_job_executed:false,
  source_provenance:'live_procureflow_postgresql_verified_evidence',
  blocks:[{id:'N01',real_data:true,simulation_only:false,job_enqueued:false,
    status:'blocked',features:[{feature_no:1,acceptance:'missing',missing_gates:['official_source']}],
    output_value:{evidence_verified:false,missing_evidence_keys:['official_source']}}]
};
const ctx=(params=getParam,http=async()=>blocked)=>({
  getInputData:()=>[{json:{}}],
  getNodeParameter:params,
  helpers:{httpRequest:http}
});
test.after(()=>{for(const [k,v] of Object.entries(original))v===undefined?delete process.env[k]:process.env[k]=v;fs.rmSync(dir,{recursive:true,force:true});});
test('exactly one official node kind carries 43 manifest operation IDs',()=>{
  const n=new ProcureFlowBusinessOperation();
  assert.equal(n.description.name,'procureFlowBusinessOperation');
  assert.deepEqual(n.description.outputNames,['success','hold_or_error']);
  const choices=n.description.properties.find(x=>x.name==='operationId').options;
  assert.equal(choices.length,43);
  assert.equal(new Set(choices.map(x=>x.value)).size,43);
});
test('disallow any external URL, credentials, nonselected case, or unapproved mode',async()=>{
  configure();
  process.env.PROCUREFLOW_OPERATION_API_BASE='https://evil.test';
  assert.throws(()=>safeApiBase(),/blocked/);
  process.env.PROCUREFLOW_OPERATION_API_BASE='http://127.0.0.1:58491';
  assert.equal(safeApiBase(),'http://127.0.0.1:58491');
  process.env.PROCUREFLOW_BUSINESS_READONLY_ENABLED='0';
  await assert.rejects(()=>new ProcureFlowBusinessOperation().execute.call(ctx()),/disabled/);
  configure();
  await assert.rejects(()=>new ProcureFlowBusinessOperation().execute.call(
    ctx(n=>n==='operationId'?'Z999':getParam(n))),/Unregistered/);
  await assert.rejects(()=>new ProcureFlowBusinessOperation().execute.call(
    ctx(n=>n==='bidNo'?'UNSELECTED':getParam(n))),/Unsupported tender/);
});
test('blocked official evidence remains HOLD, never submitted or marked verified',async()=>{
  configure();
  let count=0;
  const res=await new ProcureFlowBusinessOperation().execute.call(ctx(getParam,async options=>{
    count++;assert.equal(options.method,'GET');
    assert.equal(options.url,'http://127.0.0.1:58491/api/n8n/operational/flows/PF01/inspect');
    return blocked;
  }));
  assert.equal(count,1);
  assert.equal(res[0].length,0);
  assert.equal(res[1].length,1);
  const x=res[1][0].json;
  assert.equal(x.operation_id,'N01');
  assert.equal(x.inspection_status,'HOLD');
  assert.equal(x.evidence_verified,false);
  assert.equal(x.actual_business_handler_executed,false);
  assert.equal(x.worker_job_enqueued,false);
  assert.equal(x.bid_submitted,false);
  assert.equal(x.output,null);
});
test('unverified evidence stops native n8n branch by default',async()=>{
  configure();
  await assert.rejects(()=>new ProcureFlowBusinessOperation().execute.call(ctx(
    name=>name==='evidenceHandling'?'stop':getParam(name))),/official evidence incomplete/);
});
test('reject fake provenance and inconsistent JSON before returning any item',async()=>{
  configure();
  assert.throws(()=>validateProvenance({...blocked,simulation_only:true},'PF01','R26BK01787028','N01'),/contract mismatch/);
  assert.throws(()=>validateProvenance({...blocked,blocks:[{...blocked.blocks[0],job_enqueued:true}]},'PF01','R26BK01787028','N01'),/contract mismatch/);
});
