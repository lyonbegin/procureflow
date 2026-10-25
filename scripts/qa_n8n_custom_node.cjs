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
 console.log('N8N_CUSTOM_104_BUSINESS_NODE_PASSED operations=104 modes=3 secure_auth=true');
})().catch(e=>{console.error(e);process.exitCode=1;});
