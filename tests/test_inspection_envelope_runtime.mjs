/**
 * Execute the ACTUAL isolated ProcureFlow n8n read-only custom node for each
 * of the 43 manifest operations, then validate its emitted JSON against the
 * generated JSON Schema 2020-12 with Ajv. No HTTP server, DB or credentials.
 * This proves inspection-envelope compatibility, NOT 43 business handlers.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import Ajv2020 from 'ajv/dist/2020.js';
import {createInspectionEnvelopeSchemas} from '../n8n/source-build/inspection-envelope-schemas.mjs';

const manifest=JSON.parse(fs.readFileSync('n8n/operational_manifest.json','utf8'));
const {schemas,count,actualBusinessHandlersWithStrictPayloadSchemas,scope}=
  createInspectionEnvelopeSchemas(manifest);
assert.equal(count,43);
assert.equal(actualBusinessHandlersWithStrictPayloadSchemas,0);
assert.equal(scope,'READ_ONLY_INSPECTION_NOT_BUSINESS_HANDLER');
const owner=new Map(manifest.flows.flatMap(f=>(f.owned_blocks||[]).map(id=>[id,f.id])));
const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'pf-inspection-envelope-runtime-'));
fs.copyFileSync('n8n/custom-nodes/ProcureFlowBusinessOperation.node.js',
  path.join(tmp,'ProcureFlowBusinessOperation.node.js'));
fs.copyFileSync('n8n/operational_manifest.json',path.join(tmp,'operational_manifest.json'));
const {ProcureFlowBusinessOperation}=createRequire(import.meta.url)(
  path.join(tmp,'ProcureFlowBusinessOperation.node.js'));
const envNames=[
  'PROCUREFLOW_BUSINESS_READONLY_ENABLED','PROCUREFLOW_OPERATION_API_BASE',
  'PROCUREFLOW_OPERATION_TEST_MODE','PROCUREFLOW_APPROVED_TEST_FIXTURE_PORT',
  'PROCUREFLOW_ALLOW_INTERNAL_READONLY','PROCUREFLOW_APPROVED_INTERNAL_API_HOST',
  'PROCUREFLOW_APPROVED_INTERNAL_API_PORT','PROCUREFLOW_APPROVED_INTERNAL_API_SCHEME'
];
const oldEnv=Object.fromEntries(envNames.map(k=>[k,process.env[k]]));
test.after(()=>{
  for(const [k,v] of Object.entries(oldEnv)) {
    if(v===undefined)delete process.env[k];else process.env[k]=v;
  }
  fs.rmSync(tmp,{recursive:true,force:true});
});
function isolate(){
  process.env.PROCUREFLOW_BUSINESS_READONLY_ENABLED='1';
  process.env.PROCUREFLOW_OPERATION_TEST_MODE='1';
  process.env.PROCUREFLOW_OPERATION_API_BASE='http://127.0.0.1:58491';
  process.env.PROCUREFLOW_APPROVED_TEST_FIXTURE_PORT='58491';
  for(const k of envNames.slice(4))delete process.env[k];
}
const ajv=new Ajv2020({allErrors:true,strict:true});
const byId=new Map(schemas.map(s=>[s.operationId,s]));
assert.equal(byId.size,43);
const invalidChanges=[
  ['forged submission',x=>{x.bid_submitted=true;}],
  ['forged worker dispatch',x=>{x.worker_job_enqueued=true;}],
  ['forged actual business handler',x=>{x.actual_business_handler_executed=true;}],
  ['forged automatic submission',x=>{x.automatic_bid_submission=true;}],
  ['forged job execution',x=>{x.actual_job_executed=true;}],
  ['forged decision',x=>{x.final_decision='READY_FOR_MANUAL_PARTICIPATION';}],
  ['forged manual approval',x=>{x.manual_review_required=false;}],
  ['forged verified evidence',x=>{x.evidence_verified=true;}],
  ['forged VERIFIED with synthetic provenance',x=>{x.inspection_status='VERIFIED';}],
  ['foreign operation',x=>{x.operation_id='UNLISTED';}],
  ['foreign flow',x=>{x.flow_id='PF99';}],
  ['foreign feature contract',x=>{x.feature_ids=[999];}],
  ['untrusted evidence key',x=>{x.missing_evidence=['serviceKey=secret'];}],
  ['untrusted output',x=>{x.output={bid_submitted:true};}],
  ['unknown secret field',x=>{x.serviceKey='DO_NOT_EMIT';}]
];
test('43 isolated n8n node HOLD outputs match strict JSON Schema 2020-12; forged approval rejected',async()=>{
  isolate();
  let checked=0,rejected=0,requests=0;
  for(const block of manifest.blocks){
    const flowId=owner.get(block.id);
    assert.equal(typeof flowId,'string');
    const s=byId.get(block.id);
    assert.equal(s.flowId,flowId);
    const validateParams=ajv.compile(s.inputParameters);
    const validateOutput=ajv.compile(s.outputItem);
    const params={operationId:block.id,bidNo:'R26BK01787028',evidenceHandling:'hold'};
    assert.equal(validateParams(params),true,block.id+' valid params');
    for(const invalid of [
      {...params,operationId:'UNLISTED'},
      {...params,bidNo:'ANOTHER_CASE'},
      {...params,evidenceHandling:'submit'},
      {...params,serviceKey:'LEAK'}
    ]){assert.equal(validateParams(invalid),false,block.id+' invalid params');rejected++;}
    const synthetic={
      flow_id:flowId,case_id:'R26BK01787028',read_only:true,
      simulation_only:true,actual_job_executed:false,
      source_provenance:'isolated_synthetic_test_evidence',
      automatic_bid_submission:false,workflow_execution_engine:'native_n8n_only',
      blocks:[{id:block.id,input:block.input,output:block.output,
        real_data:false,simulation_only:true,job_enqueued:false,
        status:'blocked',features:[],
        output_value:{evidence_verified:false,missing_evidence_keys:['official_source']}}]
    };
    const ctx={
      // A forged dispatch claim now fails in preflight; this control carries
      // an untrusted decision and secret but explicitly NO dispatch.
      getInputData:()=>[{json:{bid_no:'R26BK01787028',final_decision:'SUBMIT',
        serviceKey:'DO_NOT_EMIT',worker_job_enqueued:false}}],
      getNodeParameter:name=>params[name],
      helpers:{httpRequest:async options=>{
        requests++;
        assert.equal(options.method,'GET');
        assert.equal(options.disableFollowRedirect,true);
        assert.equal(options.url,'http://127.0.0.1:58491/api/n8n/operational/flows/'+flowId+'/inspect');
        return synthetic;
      }}
    };
    // Even a malicious upstream claim must be rejected BEFORE the mocked
    // HTTP helper is reached. Check this for every one of the 43 operations.
    const forbiddenCtx={...ctx,
      getInputData:()=>[{json:{bid_no:'R26BK01787028',worker_job_enqueued:true}}],
      helpers:{httpRequest:async()=>{throw Error('FORGED_UPSTREAM_REACHED_HTTP');}}
    };
    await assert.rejects(
      ()=>new ProcureFlowBusinessOperation().execute.call(forbiddenCtx),
      /upstream read-only preflight blocked/,
      block.id+' forged dispatch claim must be rejected before GET'
    );
    const result=await new ProcureFlowBusinessOperation().execute.call(ctx);
    assert.equal(result[0].length,0,block.id+' must not enter success output');
    assert.equal(result[1].length,1,block.id+' must enter HOLD output');
    const actual=result[1][0].json;
    assert.equal(validateOutput(actual),true,
      block.id+' schema errors: '+JSON.stringify(validateOutput.errors));
    assert.equal(actual.inspection_status,'HOLD');
    assert.equal(actual.evidence_provenance,'isolated_synthetic_test_evidence');
    assert.equal(actual.actual_business_handler_executed,false);
    assert.equal(actual.bid_submitted,false);
    assert.equal(actual.worker_job_enqueued,false);
    assert.equal(JSON.stringify(actual).includes('DO_NOT_EMIT'),false);
    checked++;
    for(const [label,mutate] of invalidChanges){
      const forged=structuredClone(actual);
      mutate(forged);
      assert.equal(validateOutput(forged),false,block.id+' accepted '+label);
      rejected++;
    }
  }
  assert.equal(checked,43);
  assert.equal(requests,43);
  assert.equal(rejected,43*(4+invalidChanges.length));
  console.log('PROCUREFLOW_43_ACTUAL_ISOLATED_INSPECTION_ENVELOPES_SCHEMA_PASS',JSON.stringify({
    executedReadOnlyNodeOperations:checked,
    loopbackMockGET:requests,
    forgedEnvelopeAndParameterCasesRejected:rejected,
    actualBusinessHandlers:0,
    realOfficialG2BEvidence:0,
    actualBids:0
  }));
});


/**
 * Debugging requirement 138 (HTTP failures), 139 (timeout failure path) and
 * 158 (secrets in native execution logs): run the REAL custom n8n node
 * against injected in-memory responses. This is NOT a production endpoint,
 * business handler, actual timeout clock test, or full 80-item acceptance.
 */
test('43 actual read-only n8n operations fail closed on HTTP, provenance, approval and parameter injection',async()=>{
  isolate();
  const BID='R26BK01787028';
  const SECRET='DO_NOT_EMIT_PROVIDER_TOKEN';
  let executed=0,requests=0,blockedBeforeRequest=0,redacted=0,syntheticApprovalHeld=0;
  const makeSynthetic=(block,flowId,missing=['official_source'])=>({
    flow_id:flowId,case_id:BID,read_only:true,
    simulation_only:true,actual_job_executed:false,
    source_provenance:'isolated_synthetic_test_evidence',
    automatic_bid_submission:false,workflow_execution_engine:'native_n8n_only',
    official_notice_verified:true,business_state:'VERIFIED',
    official_detail10:[{source:'synthetic_never_official'}],
    blocks:[{
      id:block.id,input:block.input,output:block.output,
      real_data:false,simulation_only:true,job_enqueued:false,
      status:'verified',
      features:block.features.map(feature_no=>({
        feature_no,acceptance:'verified',missing_gates:[]
      })),
      output_value:{
        evidence_verified:true,real_api_result_state:'verified',
        missing_evidence_keys:missing
      }
    }]
  });
  const execute=async(block,flowId,params,upstream,reply)=>{
    let called=0;
    const ctx={
      getInputData:()=>[{json:upstream}],
      getNodeParameter:name=>params[name],
      helpers:{httpRequest:async options=>{
        called++;requests++;
        assert.equal(options.method,'GET');
        assert.equal(options.disableFollowRedirect,true);
        assert.equal(options.timeout,30000);
        assert.equal(options.url,
          'http://127.0.0.1:58491/api/n8n/operational/flows/'+flowId+'/inspect');
        assert.deepEqual(options.qs,{bid_no:BID});
        return reply();
      }}
    };
    try{
      return {result:await new ProcureFlowBusinessOperation().execute.call(ctx),called};
    }catch(error){return {error,called};}
  };
  for(const block of manifest.blocks){
    const flowId=owner.get(block.id);
    const params={operationId:block.id,bidNo:BID,evidenceHandling:'hold'};
    const upstream={bid_no:BID,serviceKey:SECRET,final_decision:'SUBMIT'};
    // The HTTP helper may throw an error containing raw request headers or
    // credentials. Only the fixed operation ID is allowed in n8n error logs.
    const network=await execute(block,flowId,params,upstream,()=>{
      throw Error('HTTP 503 timeout Authorization: Bearer '+SECRET);
    });
    assert.equal(network.called,1);
    assert.equal(network.error?.message,
      'Business Operation '+block.id+': read-only evidence request failed');
    assert.equal(network.error.message.includes(SECRET),false);
    executed++;
    // A synthetic fixture that forges ALL business verification fields must
    // still be routed to HOLD; no synthetic provenance can authorize success.
    const forged=await execute(block,flowId,params,upstream,
      ()=>makeSynthetic(block,flowId));
    assert.equal(forged.called,1);
    assert.equal(forged.result?.[0].length,0);
    assert.equal(forged.result?.[1].length,1);
    const item=forged.result[1][0].json;
    assert.equal(item.inspection_status,'HOLD');
    assert.equal(item.evidence_verified,false);
    assert.equal(item.actual_business_handler_executed,false);
    assert.equal(item.bid_submitted,false);
    assert.equal(item.worker_job_enqueued,false);
    assert.equal(item.final_decision,'HOLD');
    assert.equal(JSON.stringify(item).includes(SECRET),false);
    syntheticApprovalHeld++;
    // An upstream "missing evidence" field may contain a bearer token.
    const badKey=await execute(block,flowId,params,upstream,
      ()=>makeSynthetic(block,flowId,['official_source','Bearer '+SECRET]));
    assert.equal(badKey.called,1);
    assert.deepEqual(badKey.result?.[1][0].json.missing_evidence,
      ['official_source','redacted_evidence_key']);
    assert.equal(JSON.stringify(badKey.result).includes(SECRET),false);
    redacted++;
    // The default STOP mode must stop on synthetic/incomplete evidence.
    const stop=await execute(block,flowId,{...params,evidenceHandling:'stop'},
      upstream,()=>makeSynthetic(block,flowId));
    assert.equal(stop.called,1);
    assert.equal(stop.error?.message,
      'Business Operation '+block.id+' held: official evidence incomplete');
    executed++;
    // Mismatched official provenance fails closed and does not print
    // untrusted response content.
    const mismatch=await execute(block,flowId,params,upstream,
      ()=>({...makeSynthetic(block,flowId),flow_id:'PF99',serviceKey:SECRET}));
    assert.equal(mismatch.called,1);
    assert.equal(mismatch.error?.message,
      'Business Operation official evidence response contract mismatch');
    assert.equal(mismatch.error.message.includes(SECRET),false);
    executed++;
    // Imported JSON can bypass dropdown validation; block BEFORE any HTTP.
    for(const [changed,changedUpstream] of [
      [{...params,evidenceHandling:'submit'},upstream],
      [{...params,operationId:'UNLISTED'},upstream],
      [{...params,bidNo:'R26BK00000000'},upstream],
      [params,{...upstream,bid_no:'R26BK00000000'}]
    ]){
      const blocked=await execute(block,flowId,changed,changedUpstream,
        ()=>{throw Error('UNREACHABLE');});
      assert.equal(blocked.called,0,block.id+' invalid parameters reached HTTP');
      assert.ok(blocked.error,block.id+' invalid parameters accepted');
      assert.equal(blocked.error.message.includes(SECRET),false);
      blockedBeforeRequest++;
    }
  }
  assert.equal(executed,43*3);
  assert.equal(requests,43*5);
  assert.equal(blockedBeforeRequest,43*4);
  assert.equal(redacted,43);
  assert.equal(syntheticApprovalHeld,43);
  console.log('PROCUREFLOW_43_READONLY_FAILURE_INJECTION_PASS',JSON.stringify({
    realCustomNodeOperations:43,isolatedMockRequests:requests,
    failClosedNetworkProvenanceAndStop:executed,
    invalidParametersBlockedBeforeHTTP:blockedBeforeRequest,
    syntheticApprovalAttemptsHeld:syntheticApprovalHeld,
    providerAndUpstreamSecretsRedacted:redacted,
    actualBusinessHandlers:0,realOfficialG2BEvidence:0,actualBids:0,
    debugScope:'limited synthetic HTTP failure and redaction paths, not 80/80'
  }));
});
