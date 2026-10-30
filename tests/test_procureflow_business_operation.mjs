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
  PROCUREFLOW_APPROVED_INTERNAL_API_PORT:process.env.PROCUREFLOW_APPROVED_INTERNAL_API_PORT,
  PROCUREFLOW_APPROVED_INTERNAL_API_SCHEME:process.env.PROCUREFLOW_APPROVED_INTERNAL_API_SCHEME,
  PROCUREFLOW_APPROVED_TEST_FIXTURE_PORT:process.env.PROCUREFLOW_APPROVED_TEST_FIXTURE_PORT
};
function configure(){
  process.env.PROCUREFLOW_BUSINESS_READONLY_ENABLED='1';
  process.env.PROCUREFLOW_OPERATION_API_BASE='http://127.0.0.1:58491';
  process.env.PROCUREFLOW_OPERATION_TEST_MODE='1';
  process.env.PROCUREFLOW_APPROVED_TEST_FIXTURE_PORT='58491';
  delete process.env.PROCUREFLOW_ALLOW_INTERNAL_READONLY;
  delete process.env.PROCUREFLOW_APPROVED_INTERNAL_API_HOST;
  delete process.env.PROCUREFLOW_APPROVED_INTERNAL_API_PORT;
  delete process.env.PROCUREFLOW_APPROVED_INTERNAL_API_SCHEME;
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
test('explicit falsey or malformed upstream tender identifiers are blocked before HTTP',async()=>{
  configure();
  const instance=new ProcureFlowBusinessOperation();
  let requests=0;
  const http=async()=>{requests++;return blocked;};
  for(const supplied of ['',null,0,false,'OTHER_TENDER']){
    await assert.rejects(
      ()=>instance.execute.call(ctx(getParam,http,{bid_no:supplied})),
      error=>error.message==='Unsupported tender: official single-case gate',
      'unexpected acceptance of '+JSON.stringify(supplied)
    );
  }
  assert.equal(requests,0,'cross-tender inputs must never contact read-only API');
  // A manual trigger without an upstream case ID is valid, and a matching
  // explicit ID must still route to the selected official tender.
  const missing=await instance.execute.call(ctx(getParam,http,{}));
  const matching=await instance.execute.call(ctx(getParam,http,{bid_no:'R26BK01787028'}));
  assert.equal(missing[1].length,1);
  assert.equal(matching[1].length,1);
  assert.equal(requests,2);
});

test('multi-item batch preflight rejects later invalid inputs before ANY HTTP request',async()=>{
  configure();
  const instance=new ProcureFlowBusinessOperation();
  let requests=0;
  const http=async()=>{requests++;return blocked;};
  const run=(secondParams,secondJson)=>instance.execute.call({
    getInputData:()=>[
      {json:{bid_no:'R26BK01787028'}},
      {json:secondJson}
    ],
    getNodeParameter:(name,i)=>i===0?getParam(name):
      (Object.hasOwn(secondParams,name)?secondParams[name]:getParam(name)),
    helpers:{httpRequest:http}
  });
  const cases=[
    [{}, {bid_no:'FOREIGN_TENDER'},/Unsupported tender/],
    [{}, {bid_no:''},/Unsupported tender/],
    [{}, {bid_no:null},/Unsupported tender/],
    [{operationId:'UNKNOWN'}, {bid_no:'R26BK01787028'},/Unregistered/],
    [{evidenceHandling:'SUBMIT'}, {bid_no:'R26BK01787028'},/handling mode blocked/],
    [{bidNo:'FOREIGN_TENDER'}, {},/Unsupported tender/]
  ];
  for(const [params,json,reason] of cases){
    await assert.rejects(()=>run(params,json),reason);
    assert.equal(requests,0,'no item may trigger an HTTP request in a rejected batch');
  }
  const accepted=await run({}, {bid_no:'R26BK01787028'});
  assert.equal(requests,2,'both valid items should still issue exactly one GET each');
  assert.equal(accepted[0].length,0);
  assert.equal(accepted[1].length,2);
  assert.ok(accepted[1].every(x=>x.json.inspection_status==='HOLD'));
});


test('malformed JSON input anywhere in a batch blocks all HTTP requests',async()=>{
  configure();
  const instance=new ProcureFlowBusinessOperation();
  let requests=0;
  const http=async()=>{requests++;return blocked;};
  const good={json:{bid_no:'R26BK01787028'}};
  const malformed=[
    {json:null},{json:[]},{json:'R26BK01787028'},
    {json:42},{json:false},{json:undefined},
    {},null
  ];
  for(const bad of malformed){
    for(const inputs of [[bad,good],[good,bad]]){
      await assert.rejects(
        ()=>instance.execute.call({
          getInputData:()=>inputs,
          getNodeParameter:getParam,
          helpers:{httpRequest:http}
        }),
        error=>error.message==='Business Operation input JSON object required'
      );
      assert.equal(requests,0,'a malformed input must reject the whole batch before any GET');
    }
  }
  // An actual empty object remains a valid manual-trigger payload.
  const manual=await instance.execute.call({
    getInputData:()=>[{json:{}}],
    getNodeParameter:getParam,
    helpers:{httpRequest:http}
  });
  assert.equal(requests,1);
  assert.equal(manual[1].length,1);
  assert.equal(manual[1][0].json.inspection_status,'HOLD');
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
  assert.throws(()=>validateProvenance({...blocked,blocks:[{...blocked.blocks[0],job_enqueued:true}]},'PF01','R26BK01787028','N01'),/nested dispatch claim blocked/);
});

test('read-only provenance rejects forged top-level bid and worker dispatch claims',async()=>{
  configure();
  // Real node/manifest, stubbed HTTP only. A fake provider must not promote
  // inspection to VERIFIED when it also claims a bid or Worker dispatch.
  const instance=new ProcureFlowBusinessOperation();
  let requests=0;
  for(const field of ['bid_submitted','worker_job_enqueued','job_enqueued',
    'automated_bid_submission']){
    for(const value of [true,'true',1,null]){
      const forged={...blocked,[field]:value};
      assert.throws(()=>validateProvenance(forged,'PF01','R26BK01787028','N01'),
        /official evidence response contract mismatch/,field+'='+String(value));
      await assert.rejects(
        ()=>instance.execute.call(ctx(getParam,async()=>{requests++;return forged;})),
        /official evidence response contract mismatch/);
    }
    // Explicit false and absence are both compatible with a read-only API.
    const explicitlyFalse={...blocked,[field]:false};
    assert.equal(validateProvenance(explicitlyFalse,'PF01','R26BK01787028','N01').id,'N01');
  }
  assert.equal(requests,16,'one isolated mock response per forged claim');
  assert.equal(validateProvenance(blocked,'PF01','R26BK01787028','N01').id,'N01');
});

test('deep metadata and array dispatch claims fail closed before native output',async()=>{
  configure();
  const instance=new ProcureFlowBusinessOperation();
  let stubRequests=0;
  const forgedCases=[
    {metadata:{dispatch:{bid_submitted:true}}},
    {metadata:[{audit:[{worker_job_enqueued:'true'}]}]},
    {records:[{source:{job_enqueued:1}}]},
    {history:[{details:{automatic_bid_submission:null}}]},
    {nested:{steps:[{actual_job_executed:true}]}},
    {unrelated:{subflows:[{automated_bid_submission:true}]}}
  ];
  for(const payload of forgedCases){
    const response=structuredClone(blocked);
    response.blocks[0].output_value.extra=payload;
    assert.throws(
      ()=>validateProvenance(response,'PF01','R26BK01787028','N01'),
      /nested dispatch claim blocked/
    );
    await assert.rejects(
      ()=>instance.execute.call(ctx(getParam,async()=>{stubRequests++;return response;})),
      /nested dispatch claim blocked/
    );
  }
  // Even another block's nested metadata is untrusted and must be rejected.
  const foreign=structuredClone(blocked);
  foreign.blocks.push({id:'N02',metadata:{steps:[{bid_submitted:true}]}});
  await assert.rejects(
    ()=>instance.execute.call(ctx(getParam,async()=>{stubRequests++;return foreign;})),
    /nested dispatch claim blocked/
  );
  // A deeply nested explicit false is compatible with the read-only contract.
  const safe=structuredClone(blocked);
  safe.blocks[0].output_value.metadata={history:[{bid_submitted:false,worker_job_enqueued:false}]};
  const held=await instance.execute.call(ctx(getParam,async()=>{stubRequests++;return safe;}));
  assert.equal(held[0].length,0);
  assert.equal(held[1].length,1);
  assert.equal(held[1][0].json.inspection_status,'HOLD');
  assert.equal(stubRequests,forgedCases.length+2);
  // Bounded scanning: oversized in-memory evidence cannot hang an n8n worker.
  const huge=structuredClone(blocked);
  huge.blocks[0].output_value.metadata=Array.from({length:10050},(_,i)=>({index:i}));
  assert.throws(
    ()=>validateProvenance(huge,'PF01','R26BK01787028','N01'),
    /nested dispatch claim blocked/
  );
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
  // The nested dispatch claim is a contract violation, not a harmless
  // output field to silently omit. Verify fail-closed BEFORE checking the
  // output whitelist on a valid read-only inspection envelope.
  const node=new ProcureFlowBusinessOperation();
  await assert.rejects(
    ()=>node.execute.call(ctx(getParam,async()=>verified,{custom_secret:'SECRET_UPSTREAM_123'})),
    /nested dispatch claim blocked/,
    'forged nested bid/Worker claims must never be promoted to VERIFIED'
  );
  const safe=structuredClone(verified);
  delete safe.blocks[0].output_value.bid_submitted;
  delete safe.blocks[0].output_value.worker_job_enqueued;
  const result=await node.execute.call(
    ctx(getParam,async()=>safe,{custom_secret:'SECRET_UPSTREAM_123'}));
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

test('PF05/PF06 VERIFIED requires real 10-digit official detail codes, not merely a nonempty array',async()=>{
  configure();
  // Exercise the real native custom-node execute() with an in-memory helper.
  // This is NOT a live G2B query or proof of ten-year historical completeness.
  process.env.PROCUREFLOW_OPERATION_TEST_MODE='0';
  process.env.PROCUREFLOW_OPERATION_API_BASE='https://procureflow-api-production.up.railway.app';
  const manifest=JSON.parse(fs.readFileSync('n8n/operational_manifest.json','utf8'));
  const instance=new ProcureFlowBusinessOperation();
  let requests=0;
  for(const flowId of ['PF05','PF06']){
    const flow=manifest.flows.find(x=>x.id===flowId);
    const block=manifest.blocks.find(x=>x.id===flow.owned_blocks[0]);
    assert.ok(block,'manifest must contain an owned block for '+flowId);
    const params=name=>({operationId:block.id,bidNo:'R26BK01787028',evidenceHandling:'hold'})[name];
    const response=(codes)=>({
      flow_id:flowId,case_id:'R26BK01787028',read_only:true,
      simulation_only:false,actual_job_executed:false,
      automatic_bid_submission:false,workflow_execution_engine:'native_n8n_only',
      source_provenance:'live_procureflow_postgresql_verified_evidence',
      official_notice_verified:true,business_state:'VERIFIED',
      official_detail10:codes,
      blocks:[{
        id:block.id,input:block.input,output:block.output,
        real_data:true,simulation_only:false,job_enqueued:false,status:'verified',
        features:block.features.map(feature_no=>({feature_no,acceptance:'verified',missing_gates:[]})),
        output_value:{evidence_verified:true,real_api_result_state:'verified',missing_evidence_keys:[]}
      }]
    });
    for(const invalid of [[],['81111599'],['81111599AB'],[null],['8111159901','BAD_CODE'],[8111159901]]){
      const result=await instance.execute.call(ctx(params,async()=>{requests++;return response(invalid);}));
      assert.equal(result[0].length,0,flowId+' must not verify '+JSON.stringify(invalid));
      assert.equal(result[1].length,1,flowId+' should return HOLD');
      assert.equal(result[1][0].json.inspection_status,'HOLD');
      assert.equal(result[1][0].json.bid_submitted,false);
    }
    const valid=await instance.execute.call(ctx(params,async()=>{requests++;return response(['8111159901']);}));
    assert.equal(valid[0].length,1,flowId+' should allow a structurally valid official detail10 fixture');
    assert.equal(valid[1].length,0);
    assert.equal(valid[0][0].json.inspection_status,'VERIFIED');
    assert.equal(valid[0][0].json.actual_business_handler_executed,false);
    assert.equal(valid[0][0].json.bid_submitted,false);
  }
  assert.equal(requests,14,'two flows × six rejected shapes plus one valid fixture');
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

test('Railway internal inspection pins transport scheme as part of the exact origin',()=>{
  configure();
  process.env.PROCUREFLOW_OPERATION_TEST_MODE='0';
  process.env.PROCUREFLOW_ALLOW_INTERNAL_READONLY='1';
  process.env.PROCUREFLOW_APPROVED_INTERNAL_API_HOST='procureflow-api.railway.internal';
  const http='http://procureflow-api.railway.internal';
  const https='https://procureflow-api.railway.internal';
  process.env.PROCUREFLOW_OPERATION_API_BASE=http+'/';
  assert.equal(safeApiBase(),http,'default approved internal scheme is HTTP');
  process.env.PROCUREFLOW_OPERATION_API_BASE=https+'/';
  assert.throws(()=>safeApiBase(),/blocked/,'HTTPS cannot be silently substituted');
  process.env.PROCUREFLOW_APPROVED_INTERNAL_API_SCHEME='https';
  assert.equal(safeApiBase(),https,'explicitly approved HTTPS origin is allowed');
  process.env.PROCUREFLOW_OPERATION_API_BASE=http+'/';
  assert.throws(()=>safeApiBase(),/blocked/,'HTTP cannot downgrade approved HTTPS');
  process.env.PROCUREFLOW_APPROVED_INTERNAL_API_SCHEME='ftp';
  assert.throws(()=>safeApiBase(),/blocked/,'invalid scheme pin cannot approve an origin');
  process.env.PROCUREFLOW_APPROVED_INTERNAL_API_SCHEME='http';
  process.env.PROCUREFLOW_OPERATION_TEST_MODE='1';
  assert.throws(()=>safeApiBase(),/test mode requires isolated loopback/);
  configure();
});

test('synthetic evidence origin requires numeric loopback, not a remappable hostname',()=>{
  configure();
  for(const host of ['localhost','localhost.localdomain','127.0.0.1.nip.io',
    '127.0.0.2','[::1]']){
    process.env.PROCUREFLOW_OPERATION_API_BASE='http://'+host+':58491/';
    assert.throws(()=>safeApiBase(),/test mode requires isolated loopback|blocked/,
      'test fixture origin must reject '+host);
  }
  process.env.PROCUREFLOW_OPERATION_API_BASE='http://127.0.0.1:58491/';
  assert.equal(safeApiBase(),'http://127.0.0.1:58491');
  configure();
});


test('synthetic loopback fixture pins HTTP transport and exact approved TCP port',()=>{
  configure();
  assert.equal(safeApiBase(),'http://127.0.0.1:58491');
  for(const base of [
    'http://127.0.0.1:5855/',
    'http://127.0.0.1:58492/',
    'http://127.0.0.1:22/',
    'http://127.0.0.1/',
    'https://127.0.0.1:58491/'
  ]){
    process.env.PROCUREFLOW_OPERATION_API_BASE=base;
    assert.throws(()=>safeApiBase(),/test mode requires isolated loopback|blocked/,base);
  }
  process.env.PROCUREFLOW_OPERATION_API_BASE='http://127.0.0.1:58491/';
  for(const bad of ['058491','65536','0','abc','58491 ']){
    process.env.PROCUREFLOW_APPROVED_TEST_FIXTURE_PORT=bad;
    assert.throws(()=>safeApiBase(),/test mode requires isolated loopback|blocked/,bad);
  }
  process.env.PROCUREFLOW_APPROVED_TEST_FIXTURE_PORT='5855';
  assert.throws(()=>safeApiBase(),/test mode requires isolated loopback/,
    'test fixture port override must not silently permit the old port');
  process.env.PROCUREFLOW_OPERATION_API_BASE='http://127.0.0.1:5855/';
  assert.equal(safeApiBase(),'http://127.0.0.1:5855');
  configure();
});


test('nested block/output dispatch claims reject entire read-only inspection, including foreign blocks',async()=>{
  configure();
  const instance=new ProcureFlowBusinessOperation();
  const baseline={
    ...structuredClone(blocked),
    source_provenance:'isolated_synthetic_test_evidence',
    simulation_only:true,
    blocks:[{...structuredClone(blocked.blocks[0]),
      real_data:false,simulation_only:true}]
  };
  let requests=0;
  const execute=reply=>instance.execute.call(ctx(getParam,async()=>{
    requests++;
    return reply;
  }));
  const good=await execute(baseline);
  assert.equal(good[0].length,0);
  assert.equal(good[1].length,1);
  assert.equal(good[1][0].json.inspection_status,'HOLD');
  const flags=[
    'bid_submitted','worker_job_enqueued','job_enqueued',
    'automated_bid_submission','automatic_bid_submission','actual_job_executed'
  ];
  let rejected=0;
  for(const location of ['block','output_value']){
    for(const flag of flags){
      for(const forgedValue of [true,'true',1]){
        const forged=structuredClone(baseline);
        const target=location==='block'?forged.blocks[0]:forged.blocks[0].output_value;
        target[flag]=forgedValue;
        await assert.rejects(()=>execute(forged),/nested dispatch claim blocked/,
          location+'.'+flag+'='+String(forgedValue));
        rejected++;
      }
    }
  }
  const foreign=structuredClone(baseline);
  foreign.blocks.push({id:'N02',job_enqueued:true});
  await assert.rejects(()=>execute(foreign),/nested dispatch claim blocked/,
    'unrelated block cannot claim a queued job');
  rejected++;
  const explicitFalse=structuredClone(baseline);
  for(const flag of flags){
    explicitFalse.blocks[0][flag]=false;
    explicitFalse.blocks[0].output_value[flag]=false;
  }
  const permitted=await execute(explicitFalse);
  assert.equal(permitted[1][0].json.inspection_status,'HOLD');
  assert.equal(requests,rejected+2);
  assert.equal(rejected,37);
  console.log('PROCUREFLOW_NESTED_DISPATCH_FORGERY_BLOCKED',JSON.stringify({
    forgedNestedClaimsRejected:rejected,realHTTPRequests:0,
    mockedReadOnlyGET:requests,actualBids:0,actualWorkerDispatch:0
  }));
});
