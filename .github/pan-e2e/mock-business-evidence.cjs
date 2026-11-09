'use strict';
/**
 * Isolated n8n Chrome E2E fixture ONLY. All 43 operation IDs are generated
 * from the checked-in manifest; every response is synthetic HOLD evidence.
 * Loopback-only GET, no credentials, no G2B, no DB, no Worker or bids.
 */
const http=require('node:http');
const {readFileSync}=require('node:fs');
const manifest=JSON.parse(readFileSync('/home/node/procureflow-custom-nodes/operational_manifest.json','utf8'));
if(manifest.engine!=='n8n_only'||manifest.blocks?.length!==43||manifest.flows?.length!==15)
  throw Error('Synthetic HOLD fixture: unexpected native manifest');
const byId=new Map(manifest.blocks.map(b=>[b.id,b]));
const byFlow=new Map();
for(const flow of manifest.flows){
  const blocks=(flow.owned_blocks||[]).map(id=>{
    const block=byId.get(id);
    if(!block)throw Error('Synthetic HOLD fixture missing block '+id);
    return {
      id: block.id,input:block.input,output:block.output,
      real_data:false,simulation_only:true,job_enqueued:false,
      status:'blocked',
      features:block.features.map(feature_no=>({
        feature_no,acceptance:'missing',missing_gates:['official_source']
      })),
      output_value:{evidence_verified:false,real_api_result_state:'missing',
        missing_evidence_keys:['official_source']}
    };
  });
  byFlow.set(flow.id,blocks);
}
if([...byFlow.values()].reduce((sum,blocks)=>sum+blocks.length,0)!==43)
  throw Error('Synthetic HOLD fixture: incomplete 43-block ownership');
// Evidence of actual fixture traffic, independent of Chrome PASS labels.
// Loopback-only diagnostic; does not collect credentials, payloads or bid data.
const traffic={validReads:0,rejectedRequests:0,byFlow:Object.create(null)};
const server=http.createServer((req,res)=>{
  const u=new URL(req.url,'http://127.0.0.1:5855');
  if(req.method==='GET'&&u.pathname==='/__fixture_stats'&&!u.search){
    res.writeHead(200,{'content-type':'application/json','cache-control':'no-store'});
    res.end(JSON.stringify({schemaVersion:'procureflow.fixture-traffic.v1',
      validReads:traffic.validReads,rejectedRequests:traffic.rejectedRequests,
      byFlow:traffic.byFlow}));
    return;
  }
  const match=u.pathname.match(/^\/api\/n8n\/operational\/flows\/(PF(?:0[1-9]|1[0-5]))\/inspect$/);
  const valid=req.method==='GET'&&match&&byFlow.has(match[1])&&
    u.searchParams.get('bid_no')==='R26BK01787028'&&u.searchParams.size===1;
  if(valid){
    traffic.validReads++;
    traffic.byFlow[match[1]]=(traffic.byFlow[match[1]]||0)+1;
  }else{
    traffic.rejectedRequests++;
  }
  const body=valid?{
    flow_id:match[1],case_id:'R26BK01787028',read_only:true,
    simulation_only:true,actual_job_executed:false,
    automatic_bid_submission:false,workflow_execution_engine:'native_n8n_only',
    source_provenance:'isolated_synthetic_test_evidence',
    official_notice_verified:false,business_state:'HOLD',
    blocks:byFlow.get(match[1])
  }:{error:'isolated fixture route not found'};
  res.writeHead(valid?200:404,{'content-type':'application/json','cache-control':'no-store'});
  res.end(JSON.stringify(body));
});
server.listen(5855,'127.0.0.1',()=>console.log('ISOLATED_BUSINESS_FIXTURE_READY 127.0.0.1:5855 43-block HOLD only'));
