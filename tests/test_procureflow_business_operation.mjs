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
  PROCUREFLOW_OPERATION_TEST_MODE:process.env.PROCUREFLOW_OPERATION_TEST_MODE,
  PROCUREFLOW_ALLOW_INTERNAL_READONLY:process.env.PROCUREFLOW_ALLOW_INTERNAL_READONLY,
  PROCUREFLOW_APPROVED_INTERNAL_API_HOST:process.env.PROCUREFLOW_APPROVED_INTERNAL_API_HOST,
  PROCUREFLOW_APPROVED_INTERNAL_API_PORT:process.env.PROCUREFLOW_APPROVED_INTERNAL_API_PORT
};
function configure(){
  process.env.PROCUREFLOW_BUSINESS_READONLY_ENABLED='1';
  process.env.PROCUREFLOW_OPERATION_API_BASE='http://127.0.0.1:58491';
  process.env.PROCUREFLOW_OPERATION_TEST_MODE='1';
  delete process.env.PROCUREFLOW_ALLOW_INTERNAL_READONLY;
  delete process.env.PROCUREFLOW_APPROVED_INTERNAL_API_HOST;
  delete process.env.PROCUREFLOW_APPROVED_INTERNAL_API_PORT;
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
  assert.throws(()=>safeApiBase(),/test mode requires isolated loopback|blocked/);
  process.env.PROCUREFLOW_OPERATION_API_BASE='http://127.0.0.1:58491';
  assert.equal(safeApiBase(),'http://127.0.0.1:58491');
  process.env.PROCUREFLOW_OPERATION_API_BASE='https://procureflow-api-production.up.railway.app';
  assert.throws(()=>safeApiBase(),/test mode requires isolated loopback/);
  process.env.PROCUREFLOW_OPERATION_API_BASE='http://127.0.0.1:58491';
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
test('untrusted upstream fields and nested secrets never echo into native execution output',async()=>{
  configure();
  const injected={
    bid_no:'R26BK01787028',
    serviceKey:'PRIVATE_SERVICE_KEY_123',
    bearerToken:'PRIVATE_BEARER_123',
    bidder:{identity:'PRIVATE_BIDDER_123',bankAccount:'PRIVATE_ACCOUNT_123'},
    arbitrary_nested:{payload:['PRIVATE_NESTED_123']},
    custom_approval:'SUBMIT',
    final_decision:'SUBMIT'
  };
  const result=await new ProcureFlowBusinessOperation().execute.call(
    ctx(getParam,async()=>blocked,injected));
  assert.equal(result[0].length,0);
  assert.equal(result[1].length,1);
  const output=result[1][0].json;
  assert.equal(output.bid_no,'R26BK01787028');
  assert.equal(output.inspection_status,'HOLD');
  assert.equal(output.final_decision,'HOLD');
  assert.equal(output.bid_submitted,false);
  assert.equal(output.worker_job_enqueued,false);
  for(const field of ['serviceKey','bearerToken','bidder','arbitrary_nested','custom_approval'])
    assert.equal(Object.hasOwn(output,field),false,field);
  assert.ok(!JSON.stringify(result).includes('PRIVATE_'));
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
test('tampered imported workflow evidenceHandling is rejected before any HTTP request',async()=>{
  configure();
  const instance=new ProcureFlowBusinessOperation();
  let requests=0;
  for(const mode of ['skip','verified','SUBMIT','',null,42]){
    const params=name=>name==='evidenceHandling'?mode:getParam(name);
    await assert.rejects(
      ()=>instance.execute.call(ctx(params,async()=>{requests++;return blocked;})),
      error=>error.message==='Business Operation evidence handling mode blocked',
      String(mode)
    );
  }
  assert.equal(requests,0);
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
  // A fixture that falsely labels itself as live must NEVER produce VERIFIED
  // while the process is in isolated test mode.
  const spoofed=await instance.execute.call(ctx(getParam,async()=>inspect([1,2])));
  assert.equal(spoofed[0].length,0);
  assert.equal(spoofed[1].length,1);
  assert.equal(spoofed[1][0].json.inspection_status,'HOLD');
  // The remaining tests use a stubbed HTTP helper, not a network request,
  // to check the production-mode acceptance predicate independently.
  process.env.PROCUREFLOW_OPERATION_TEST_MODE='0';
  process.env.PROCUREFLOW_OPERATION_API_BASE='https://procureflow-api-production.up.railway.app';
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


test('verified read-only inspection whitelists output and never forwards secrets or forged approval fields',async()=>{
  configure();
  // Stubbed helper only: no network or production credential access.
  process.env.PROCUREFLOW_OPERATION_TEST_MODE='0';
  process.env.PROCUREFLOW_OPERATION_API_BASE='https://procureflow-api-production.up.railway.app';
  const verified={
    ...blocked,
    official_notice_verified:true,
    blocks:[{
      ...blocked.blocks[0],status:'verified',
      features:[1,2].map(feature_no=>({feature_no,acceptance:'verified',missing_gates:[]})),
      output_value:{
        evidence_verified:true,real_api_result_state:'verified',
        missing_evidence_keys:[],
        serviceKey:'SECRET_VERIFIED_KEY_123',
        bearerToken:'SECRET_VERIFIED_TOKEN_123',
        bidder:{bankAccount:'SECRET_VERIFIED_BANK_123'},
        bid_submitted:true,final_decision:'SUBMIT',
        worker_job_enqueued:true,
        verified_evidence_keys:['official_notice']
      }
    }]
  };
  const result=await new ProcureFlowBusinessOperation().execute.call(
    ctx(getParam,async()=>verified,{custom_secret:'SECRET_UPSTREAM_123'}));
  assert.equal(result[0].length,1);
  assert.equal(result[1].length,0);
  const item=result[0][0].json;
  assert.equal(item.inspection_status,'VERIFIED');
  assert.equal(item.actual_business_handler_executed,false);
  assert.equal(item.bid_submitted,false);
  assert.equal(item.worker_job_enqueued,false);
  assert.deepEqual(item.output,{
    evidence_verified:true,real_api_result_state:'verified',missing_evidence_keys:[]
  });
  for(const field of ['serviceKey','bearerToken','bidder','bid_submitted','final_decision','worker_job_enqueued'])
    assert.equal(Object.hasOwn(item.output,field),false,field);
  assert.ok(!JSON.stringify(result).includes('SECRET_'));
  configure();
});

test('all 43 manifest operations fail closed with isolated evidence and exact GET routing',async()=>{
  configure();
  const manifest=JSON.parse(fs.readFileSync('n8n/operational_manifest.json','utf8'));
  const owner=new Map(manifest.flows.flatMap(f=>(f.owned_blocks||[]).map(id=>[id,f.id])));
  const instance=new ProcureFlowBusinessOperation();
  assert.equal(manifest.blocks.length,43);
  let requests=0;
  for(const block of manifest.blocks){
    const flowId=owner.get(block.id);
    assert.ok(flowId,'missing owner '+block.id);
    const params=(name)=>({
      operationId:block.id,bidNo:'R26BK01787028',evidenceHandling:'hold'
    })[name];
    const fixture={
      flow_id:flowId,case_id:'R26BK01787028',
      source_provenance:'isolated_synthetic_test_evidence',
      read_only:true,simulation_only:true,actual_job_executed:false,
      automatic_bid_submission:false,workflow_execution_engine:'native_n8n_only',
      blocks:[{
        id:block.id,input:block.input,output:block.output,
        real_data:false,simulation_only:true,job_enqueued:false,
        status:'blocked',features:[],
        output_value:{evidence_verified:false,missing_evidence_keys:['official_source']}
      }]
    };
    const response=await instance.execute.call(ctx(params,async options=>{
      requests++;
      assert.equal(options.method,'GET');
      assert.equal(options.url,'http://127.0.0.1:58491/api/n8n/operational/flows/'+flowId+'/inspect');
      assert.equal(options.qs.bid_no,'R26BK01787028');
      return fixture;
    },{final_decision:'SUBMIT',bid_submitted:true,worker_job_enqueued:true}));
    assert.equal(response[0].length,0,block.id);
    assert.equal(response[1].length,1,block.id);
    const result=response[1][0].json;
    assert.equal(result.operation_id,block.id);
    assert.equal(result.flow_id,flowId);
    assert.equal(result.inspection_status,'HOLD');
    assert.equal(result.actual_business_handler_executed,false);
    assert.equal(result.evidence_verified,false);
    assert.equal(result.bid_submitted,false);
    assert.equal(result.worker_job_enqueued,false);
    assert.equal(result.final_decision,'HOLD');
  }
  assert.equal(requests,43);
});
test('provider errors and untrusted evidence keys cannot leak serviceKey into native n8n output',async()=>{
  configure();
  const instance=new ProcureFlowBusinessOperation();
  await assert.rejects(
    ()=>instance.execute.call(ctx(getParam,async()=>{
      throw Error('HTTP 500 serviceKey=TOP_SECRET_123 https://bad.test/?token=TOP_SECRET_123');
    })),
    error=>error.message==='Business Operation N01: read-only evidence request failed'&&
      !error.message.includes('TOP_SECRET_123')
  );
  const malicious={...blocked,
    blocks:[{...blocked.blocks[0],
      output_value:{evidence_verified:false,
        missing_evidence_keys:['official_source','serviceKey=TOP_SECRET_123',
          'https://bad.test/?token=TOP_SECRET_123','official_source']}}]};
  const result=await instance.execute.call(ctx(getParam,async()=>malicious));
  const keys=result[1][0].json.missing_evidence;
  assert.deepEqual(keys,['official_source','redacted_evidence_key']);
  assert.ok(!JSON.stringify(result).includes('TOP_SECRET_123'));
  const identifierSecret={...malicious,
    blocks:[{...malicious.blocks[0],output_value:{evidence_verified:false,
      missing_evidence_keys:['TOP_SECRET_123','official_source']}}]};
  const secretResult=await instance.execute.call(ctx(getParam,async()=>identifierSecret));
  assert.deepEqual(secretResult[1][0].json.missing_evidence,
    ['redacted_evidence_key','official_source']);
  assert.ok(!JSON.stringify(secretResult).includes('TOP_SECRET_123'));
  await assert.rejects(()=>instance.execute.call(ctx(
    name=>name==='operationId'?'SECRET_OPERATION_ID_123':getParam(name))),
    error=>error.message==='Unregistered Business Operation ID'&&
      !error.message.includes('SECRET_OPERATION_ID_123'));
});

test('read-only evidence HTTP helper forbids cross-origin redirects and redacts redirect errors',async()=>{
  configure();
  let called=0;
  const instance=new ProcureFlowBusinessOperation();
  await assert.rejects(
    ()=>instance.execute.call(ctx(getParam,async options=>{
      called++;
      assert.equal(options.method,'GET');
      assert.equal(options.disableFollowRedirect,true);
      assert.equal(options.url,'http://127.0.0.1:58491/api/n8n/operational/flows/PF01/inspect');
      // A real n8n helper rejects the redirect instead of contacting Location.
      throw Error('302 Location: https://evil.example/?serviceKey=REDIRECT_SECRET_123');
    })),
    error=>error.message==='Business Operation N01: read-only evidence request failed'&&
      !error.message.includes('REDIRECT_SECRET_123')
  );
  assert.equal(called,1);
});

test('production read-only API host rejects nonstandard ports without making a request',()=>{
  configure();
  process.env.PROCUREFLOW_OPERATION_TEST_MODE='0';
  const origin='https://procureflow-api-production.up.railway.app';
  for(const base of [
    origin+':4443/',
    origin+':8080/',
    'http://procureflow-api-production.up.railway.app/',
    'https://procureflow-api-production.up.railway.app.evil.test/',
    'https://evil.test@procureflow-api-production.up.railway.app/'
  ]){
    process.env.PROCUREFLOW_OPERATION_API_BASE=base;
    assert.throws(()=>safeApiBase(),/blocked|invalid|policy/,base);
  }
  process.env.PROCUREFLOW_OPERATION_API_BASE=origin+'/';
  assert.equal(safeApiBase(),origin);
  configure();
});

test('Railway internal read-only origin requires exact approved hostname, never suffix-only',()=>{
  configure();
  process.env.PROCUREFLOW_OPERATION_TEST_MODE='0';
  process.env.PROCUREFLOW_ALLOW_INTERNAL_READONLY='1';
  process.env.PROCUREFLOW_OPERATION_API_BASE='http://other-service.railway.internal/';
  assert.throws(()=>safeApiBase(),/blocked/,'suffix alone must not grant access');
  process.env.PROCUREFLOW_APPROVED_INTERNAL_API_HOST='procureflow-api.railway.internal';
  assert.throws(()=>safeApiBase(),/blocked/,'unrelated internal service must remain blocked');
  process.env.PROCUREFLOW_OPERATION_API_BASE='http://procureflow-api.railway.internal/';
  assert.equal(safeApiBase(),'http://procureflow-api.railway.internal');
  process.env.PROCUREFLOW_OPERATION_API_BASE='http://procureflow-api.railway.internal.evil.test/';
  assert.throws(()=>safeApiBase(),/blocked/,'lookalike host must be blocked');
  process.env.PROCUREFLOW_OPERATION_API_BASE='http://procureflow-api.railway.internal/';
  process.env.PROCUREFLOW_OPERATION_TEST_MODE='1';
  assert.throws(()=>safeApiBase(),/test mode requires isolated loopback/);
  configure();
});

test('Railway internal inspection pins TCP port, not only DNS hostname',()=>{
  configure();
  process.env.PROCUREFLOW_OPERATION_TEST_MODE='0';
  process.env.PROCUREFLOW_ALLOW_INTERNAL_READONLY='1';
  process.env.PROCUREFLOW_APPROVED_INTERNAL_API_HOST='procureflow-api.railway.internal';
  const host='http://procureflow-api.railway.internal';
  process.env.PROCUREFLOW_OPERATION_API_BASE=host+':8000/';
  assert.throws(()=>safeApiBase(),/blocked/,'unapproved nondefault port must be blocked');
  process.env.PROCUREFLOW_APPROVED_INTERNAL_API_PORT='8000';
  assert.equal(safeApiBase(),host+':8000');
  process.env.PROCUREFLOW_OPERATION_API_BASE=host+':8001/';
  assert.throws(()=>safeApiBase(),/blocked/,'another service port must be blocked');
  process.env.PROCUREFLOW_OPERATION_API_BASE=host+':8000/';
  for(const bad of ['08000','65536','8000 ','0','abc']){
    process.env.PROCUREFLOW_APPROVED_INTERNAL_API_PORT=bad;
    assert.throws(()=>safeApiBase(),/blocked/,bad);
  }
  delete process.env.PROCUREFLOW_APPROVED_INTERNAL_API_PORT;
  process.env.PROCUREFLOW_OPERATION_API_BASE=host+'/';
  assert.equal(safeApiBase(),host);
  process.env.PROCUREFLOW_OPERATION_TEST_MODE='1';
  process.env.PROCUREFLOW_APPROVED_INTERNAL_API_PORT='8000';
  process.env.PROCUREFLOW_OPERATION_API_BASE=host+':8000/';
  assert.throws(()=>safeApiBase(),/test mode requires isolated loopback/);
  configure();
});
