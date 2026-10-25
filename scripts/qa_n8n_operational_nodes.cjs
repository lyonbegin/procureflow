/* Test ACTUAL n8n Code-node JS of the 15 exported operational flows.
   The GET node result is a mocked HTTP *contract*, not a fake official success.
   All PF nodes must preserve missing-evidence blocks in the trace. */
const fs=require('node:fs'), vm=require('node:vm'), path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),manifest=JSON.parse(fs.readFileSync(path.join(root,'n8n/operational_manifest.json'),'utf8'));
function evalNode(code,json){
 const sandbox=Object.create(null);sandbox.$input={first:()=>({json})};
 const program=new vm.Script('(function(){\n'+code+'\n})()',{filename:'native-pf-code-node.js'});
 const result=program.runInNewContext(sandbox,{timeout:2500});
 assert.equal(result.length,1);
 return JSON.parse(JSON.stringify(result[0].json));
}
let tested=0;
for(const f of manifest.flows){
 const w=JSON.parse(fs.readFileSync(path.join(root,'n8n/operational',f.id+'.json'),'utf8'));
 const codes=w.nodes.filter(n=>n.type==='n8n-nodes-base.code' && (n.name==='01 · 발주번호·PF 흐름 선택' || n.name==='03 · 공식 증빙 검사·입력 기록' || n.name.includes(' · ') && f.owned_blocks.some(id=>n.name.startsWith(id+' · ')) || n.name==='최종 · 업무 미완료·대기·검증 결과'));
 assert.equal(codes.length,f.owned_blocks.length+3); 
 assert.equal(w.nodes.filter(n=>n.type==='n8n-nodes-base.httpRequest' && n.parameters.genericAuthType==='httpHeaderAuth').length,2);
 assert.ok(w.connections['실제 Worker Job 실행 여부']);
 const input=evalNode(codes[0].parameters.jsCode,null);tested++;
 assert.equal(input.flow_id,f.id);
 const fake={
     flow_id:f.id,flow_name:f.label,case_id:input.bid_no,source_provenance:'live_procureflow_postgresql_verified_evidence',
     read_only:true,simulation_only:false,business_state:'BLOCKED_OR_PENDING',
     nodes:f.business_features.length,blocks_total:f.owned_blocks.length,blocks_verified:0,
     pending_missing_evidence:['official_original_missing'],downstream_flows:f.next,
     blocks:f.owned_blocks.map(id=>{const b=manifest.blocks.find(x=>x.id===id);
       return {id:b.id,name:b.label,input:b.input,output:b.output,features:b.features.map(n=>({feature_no:n,acceptance:'missing',missing_gates:['official_original_missing']})),
         output_value:{missing_evidence_keys:['official_original_missing'],verified_evidence_keys:[],evidence_verified:false,real_api_result_state:'blocked'},
         next_blocks:b.to,status:'blocked'};})
 };
 let state=evalNode(codes[1].parameters.jsCode,fake);tested++;
 for(let i=0;i<f.owned_blocks.length;i++){
   state=evalNode(codes[2+i].parameters.jsCode,state);tested++;
   assert.equal(state.workflow_trace.at(-1).block_id,f.owned_blocks[i]);
   assert.equal(state.workflow_trace.at(-1).output.evidence_verified,false);
   if(i>0)assert.deepEqual(state.workflow_trace.at(-1).input.upstream,state.workflow_trace.at(-2).output);
 }
 const result=evalNode(codes.at(-1).parameters.jsCode,state);tested++;
 assert.equal(result.business_state,'BLOCKED_OR_PENDING');
 assert.equal(result.workflow_status,'PENDING_REAL_EVIDENCE');
 assert.equal(result.execution_trace.length,f.owned_blocks.length);
 assert.equal(result.actual_job_executed,false);
 assert.equal(result.simulation_only,false);
 assert.equal(result.bid_submitted,false);
}

// True n8n Code-node JS tests for the worker polling control path.
// Constructed input is an API response fixture, not an official-G2B success.
let progressTests=0;
for(const f of manifest.flows){
 const wf=JSON.parse(fs.readFileSync(path.join(root,'n8n/operational',f.id+'.json'),'utf8'));
 const poll=wf.nodes.find(n=>n.name==='실제 Worker 응답·기한 검증');
 const output=wf.nodes.find(n=>n.name==='Worker 결과·업무 완료 분리');
 assert.ok(poll&&output);
 const fake={flow_id:f.id,bid_no:'R26BK01787028',job_id:345,job_created_at:new Date().toISOString(),
   worker_terminal:false,worker_state:'running',business_state:'BLOCKED_OR_PENDING',independently_verified:false,missing_evidence:['original_not_verified']};
 const running=evalNode(poll.parameters.jsCode,fake);
 progressTests++;
 assert.equal(running.poll_end,false);
 assert.equal(running.poll_timed_out,false);
 assert.equal(running.bid_submitted,false);
 const finished=evalNode(poll.parameters.jsCode,{...fake,worker_terminal:true,worker_state:'completed',independently_verified:false});
 progressTests++;
 assert.equal(finished.poll_end,true);
 const summary=evalNode(output.parameters.jsCode,finished);
 progressTests++;
 assert.equal(summary.workflow_state,'COLLECTED_BUT_EVIDENCE_PENDING');
 assert.equal(summary.independently_verified,false);
 assert.equal(summary.job_executed,true);
 const stale=evalNode(poll.parameters.jsCode,{...fake,job_created_at:new Date(Date.now()-16*60*1000).toISOString()});
 progressTests++;
 assert.equal(stale.poll_timed_out,true);
 assert.equal(stale.poll_end,true);
 const failed=evalNode(output.parameters.jsCode,evalNode(poll.parameters.jsCode,{...fake,worker_terminal:true,worker_state:'failed',worker_error:'official source timeout'}));
 progressTests++;
 assert.equal(failed.workflow_state,'WORKER_FAILED');
 assert.equal(failed.requires_operator_check,true);
 assert.equal(failed.worker_error,'official source timeout');
 const cancelled=evalNode(output.parameters.jsCode,evalNode(poll.parameters.jsCode,{...fake,worker_terminal:true,worker_state:'cancelled'}));
 progressTests++;
 assert.equal(cancelled.workflow_state,'WORKER_CANCELLED');
 const partial=evalNode(output.parameters.jsCode,evalNode(poll.parameters.jsCode,{...fake,worker_terminal:true,worker_state:'completed_partial'}));
 progressTests++;
 assert.equal(partial.workflow_state,'WORKER_PARTIAL');
 const timeoutResult=evalNode(output.parameters.jsCode,stale);
 progressTests++;
 assert.equal(timeoutResult.workflow_state,'POLL_TIMED_OUT');
 assert.equal(timeoutResult.requires_operator_check,true);
 assert.equal(timeoutResult.job_executed,false);
 const invalid=evalNode(poll.parameters.jsCode,{...fake,job_created_at:'bad-date'});
 progressTests++;
 assert.equal(invalid.poll_timed_out,true);
 assert.throws(()=>evalNode(poll.parameters.jsCode,{...fake,bid_no:'R26BK_BAD'}),/identity mismatch/);
 assert.throws(()=>evalNode(output.parameters.jsCode,running),/polling mismatch/);
 assert.equal(wf.connections['Worker 완료 또는 시간 초과?'].main[1][0].node,'Worker 처리 대기 · 20초');
}
console.log('N8N_WORKER_POLL_CONTROL_PASSED flows=15 cases='+progressTests);

console.log('N8N_15_OPERATIONAL_NATIVE_JS_PASSED flows=15 blocks=43 nodes_executed='+tested);
