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
console.log('N8N_15_OPERATIONAL_NATIVE_JS_PASSED flows=15 blocks=43 nodes_executed='+tested);
