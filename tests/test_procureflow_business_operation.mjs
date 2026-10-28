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
  automatic_bid_submission:false,workflow_execution_engine:'native_n8n_only',
  blocks:[{id:'N01',input:'query.window',output:'tender_candidates[]',
    real_data:true,simulation_only:false,job_enqueued:false,
    status:'blocked',features:[{feature_no:1,acceptance:'missing',missing_gates:['official_source']}],
    output_value:{evidence_verified:false,missing_evidence_keys:['official_source']}}]
};
const ctx=(params=getParam,http=async()=>blocked,upstream={})=>({
  getInputData:()=>[{json:upstream}],
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
test('untrusted upstream approval and bid flags cannot bypass inspection-only HOLD',async()=>{
  configure();
  const injected={bid_no:'R26BK01787028',final_decision:'SUBMIT',
    manual_review_required:false,workflow_status:'APPROVED',
    read_only:false,automatic_bid_submission:true,
    automated_bid_submission:true,actual_job_executed:true,
    job_enqueued:true,worker_job_enqueued:true,bid_submitted:true,
    evidence_verified:true,inspection_status:'VERIFIED'};
  const res=await new ProcureFlowBusinessOperation().execute.call(
    ctx(getParam,async()=>blocked,injected));
  assert.equal(res[0].length,0);
  assert.equal(res[1].length,1);
  const actual=res[1][0].json;
  for(const key of ['automatic_bid_submission','automated_bid_submission',
    'actual_job_executed','job_enqueued','worker_job_enqueued',
    'bid_submitted','evidence_verified'])assert.equal(actual[key],false,key);
  assert.equal(actual.final_decision,'HOLD');
  assert.equal(actual.manual_review_required,true);
  assert.equal(actual.workflow_status,'OFFICIAL_EVIDENCE_INSPECTION_ONLY');
  assert.equal(actual.read_only,true);
  assert.equal(actual.inspection_status,'HOLD');
});
test('isolated synthetic provenance is explicit, never VERIFIED, and blocked outside test mode',async()=>{
  configure();
  const synthetic={...blocked,source_provenance:'isolated_synthetic_test_evidence',
    simulation_only:true,official_notice_verified:true,
    blocks:[{...blocked.blocks[0],real_data:false,simulation_only:true,
      status:'verified',features:[
        {feature_no:1,acceptance:'verified',missing_gates:[]},
        {feature_no:2,acceptance:'verified',missing_gates:[]}],
      output_value:{evidence_verified:true,real_api_result_state:'verified',
        missing_evidence_keys:[]}}]};
  const result=await new ProcureFlowBusinessOperation().execute.call(ctx(getParam,async()=>synthetic));
  assert.equal(result[0].length,0);
  assert.equal(result[1].length,1);
  assert.equal(result[1][0].json.inspection_status,'HOLD');
  assert.equal(result[1][0].json.evidence_provenance,'isolated_synthetic_test_evidence');
  process.env.PROCUREFLOW_OPERATION_TEST_MODE='0';
  assert.throws(()=>validateProvenance(synthetic,'PF01','R26BK01787028','N01'),/contract mismatch/);
  configure();
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

test('reject duplicate blocks, wrong input/output and simulated execution flags',()=>{
  assert.throws(()=>validateProvenance({...blocked,blocks:[blocked.blocks[0],blocked.blocks[0]]},'PF01','R26BK01787028','N01'),/unique block/);
  assert.throws(()=>validateProvenance({...blocked,blocks:[{...blocked.blocks[0],input:'wrong'}]},'PF01','R26BK01787028','N01'),/block\/official/);
  assert.throws(()=>validateProvenance({...blocked,automatic_bid_submission:true},'PF01','R26BK01787028','N01'),/response contract/);
  assert.throws(()=>validateProvenance({...blocked,workflow_execution_engine:'mock'},'PF01','R26BK01787028','N01'),/response contract/);
});
test('exact manifest feature IDs are required for VERIFIED; wrong IDs remain HOLD',async()=>{
  configure();
  const feature=(feature_no)=>({feature_no,acceptance:'verified',missing_gates:[]});
  const inspect=(ids)=>({...blocked,official_notice_verified:true,
    blocks:[{...blocked.blocks[0],status:'verified',
      features:ids.map(feature),
      output_value:{evidence_verified:true,real_api_result_state:'verified',
        missing_evidence_keys:[],verified_evidence_keys:['official_notice']}}]});
  const instance=new ProcureFlowBusinessOperation();
  const good=await instance.execute.call(ctx(getParam,async()=>inspect([1,2])));
  assert.equal(good[0].length,1);
  assert.equal(good[1].length,0);
  assert.equal(good[0][0].json.inspection_status,'VERIFIED');
  assert.equal(good[0][0].json.actual_business_handler_executed,false);
  assert.equal(good[0][0].json.bid_submitted,false);
  const wrong=await instance.execute.call(ctx(getParam,async()=>inspect([1,3])));
  assert.equal(wrong[0].length,0);
  assert.equal(wrong[1].length,1);
  assert.equal(wrong[1][0].json.inspection_status,'HOLD');
  const duplicate=await instance.execute.call(ctx(getParam,async()=>inspect([1,1])));
  assert.equal(duplicate[0].length,0);
  assert.equal(duplicate[1].length,1);
});
