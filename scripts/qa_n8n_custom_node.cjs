const assert=require('node:assert/strict');
const path=require('node:path');
const base=path.resolve(__dirname,'../n8n/custom_nodes/n8n-nodes-procureflow');
const {ProcureFlow}=require(base+'/dist/nodes/ProcureFlow.node.js');
const {ProcureFlowApi}=require(base+'/dist/credentials/ProcureFlowApi.credentials.js');
const node=new ProcureFlow();
const credential=new ProcureFlowApi();
assert.equal(node.description.name,'procureFlow');
assert.equal(node.description.credentials[0].name,'procureFlowApi');
assert.equal(credential.properties.find(x=>x.name==='adminToken').typeOptions.password,true);
const selector=node.description.properties.find(x=>x.name==='featureNo');
assert.equal(selector.options.length,104);
assert.deepEqual(selector.options.map(x=>x.value),Array.from({length:104},(_,i)=>i+1));
const executions=[];
async function execute(operation,number,params,bid='R26BK01787028'){
  let token='ci-internal-only-token';
  const ctx={
    getInputData:()=>[{json:{source:'upstream'}}],
    getCredentials:async()=>({baseUrl:'https://procureflow-api-production.up.railway.app',adminToken:token}),
    getNodeParameter:(key)=>({featureNo:number,operation,bidNo:bid,parameters:params})[key],
    helpers:{httpRequest:async(req)=>{
      executions.push(req);
      return {status:operation==='collect'?'queued':'missing',real_business_complete:false};
    }},
  };
  const out=await node.execute.call(ctx);
  assert.equal(out[0].length,1);
  assert.equal(out[0][0].json.bid_submitted,false);
  assert.equal(JSON.stringify(out).includes(token),false);
  return out[0][0].json;
}

async function flowAction(operation,input) {
  const token="ci-native-credential-not-visible";
  const ctx={
    getInputData:()=>[{json:input}],
    getCredentials:async()=>({baseUrl:"https://procureflow-api-production.up.railway.app",adminToken:token}),
    getNodeParameter:(key)=>({flowId:"PF05",operation,bidNo:"R26BK01787028"})[key],
    helpers:{httpRequest:async(req)=>{executions.push(req);return operation==="dispatchPlanned"?
      {job_id:321,state:"queued",feature_no:49}:operation==="jobStatus"?
      {job_id:321,worker_state:"completed",worker_terminal:true,
       independently_verified:false,missing_evidence:["outcome_10years_complete"],
       business_state:"BLOCKED_OR_PENDING"}:
      {status:"ACTIONABLE",flow_id:"PF05",bid_no:"R26BK01787028",candidate:{feature_no:49},request_key:"a-valid-test-token"};}}
  };
  const result=await node.execute.call(ctx);
  assert.equal(result[0][0].json.bid_submitted,false);
  assert.equal(JSON.stringify(result).includes(token),false);
  return result[0][0].json;
}

(async()=>{
 const a=await execute('inspect',1,'{}');assert.equal(a.job_requested,false);
 assert.equal(executions.at(-1).method,'GET');
 assert.ok(executions.at(-1).url.endsWith('/features/1'));
 const b=await execute('check',50,'{"candidate_limit":2}');
 assert.equal(executions.at(-1).body.mode,'check');
 assert.equal(executions.at(-1).body.parameters.candidate_limit,2);
 const c=await execute('collect',50,'{"opening_limit":2}');
 assert.equal(c.job_requested,true);
 assert.equal(executions.at(-1).body.mode,'collect');
 assert.ok(executions.at(-1).url.endsWith('/features/50/run'));
 assert.equal(executions.at(-1).headers.Authorization,'Bearer ci-internal-only-token');
 await assert.rejects(execute('collect',50,'{"detail10":"forged"}'),/원본 공고/);
 await assert.rejects(execute('collect',105,'{}'),/Invalid official/);
 await assert.rejects(execute('collect',1,'{"bid_no":"foo"}'),/원본 공고/);
 const plan=await flowAction("planNext",{});
 assert.equal(plan.response.status,"ACTIONABLE");
 assert.ok(executions.at(-1).url.endsWith("/api/n8n/operational/flows/PF05/next-action?bid_no=R26BK01787028"));
 const dispatch=await flowAction("dispatchPlanned",{
   status:"ACTIONABLE",flow_id:"PF05",bid_no:"R26BK01787028",
   request_key:"a-valid-test-token",candidate:{feature_no:49}
 });
 assert.equal(dispatch.job_id,321);
 assert.equal(executions.at(-1).method,"POST");
 assert.equal(executions.at(-1).body.request_key,"a-valid-test-token");
 assert.equal(executions.at(-1).body.feature_no,49);
 assert.ok(executions.at(-1).url.endsWith("/api/n8n/operational/flows/PF05/dispatch"));
 const job=await flowAction("jobStatus",{job_id:321});
 assert.equal(job.independently_verified,false);
 assert.equal(job.business_state,"BLOCKED_OR_PENDING");
 assert.ok(executions.at(-1).url.includes("/jobs/321?bid_no=R26BK01787028"));
 await assert.rejects(flowAction("dispatchPlanned",{
   status:"ACTIONABLE",flow_id:"PF05",bid_no:"FORGED",
   request_key:"a-valid-test-token",candidate:{feature_no:49}
 }),/mismatch/);
 await assert.rejects(flowAction("dispatchPlanned",{status:"BLOCKED",candidate:null}),/not ACTIONABLE/);

 console.log('N8N_CUSTOM_104_BUSINESS_NODE_PASSED operations=104 modes=6 secure_auth=true');
})().catch(e=>{console.error(e);process.exitCode=1;});
