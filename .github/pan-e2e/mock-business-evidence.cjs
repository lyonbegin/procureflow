'use strict';
/**
 * Isolated n8n Chrome E2E fixture ONLY. Loopback-only, GET-only, no G2B,
 * no credentials, no DB, no Worker, no bid submission. This fixture MUST
 * never claim real official evidence or mark a business block verified.
 */
const http=require('node:http');
const payload={
  flow_id:'PF01',case_id:'R26BK01787028',read_only:true,
  simulation_only:true,actual_job_executed:false,
  automatic_bid_submission:false,workflow_execution_engine:'native_n8n_only',
  source_provenance:'isolated_synthetic_test_evidence',
  official_notice_verified:false,
  blocks:[{id:'N01',input:'query.window',output:'tender_candidates[]',
    real_data:false,simulation_only:true,job_enqueued:false,
    status:'blocked',features:[
      {feature_no:1,acceptance:'missing',missing_gates:['official_source']},
      {feature_no:2,acceptance:'missing',missing_gates:['official_source']}],
    output_value:{evidence_verified:false,real_api_result_state:'missing',
      missing_evidence_keys:['official_source']}}]
};
const server=http.createServer((req,res)=>{
  const u=new URL(req.url,'http://127.0.0.1:5855');
  const valid=req.method==='GET'&&u.pathname==='/api/n8n/operational/flows/PF01/inspect'&&
    u.searchParams.get('bid_no')==='R26BK01787028'&&u.searchParams.size===1;
  res.writeHead(valid?200:404,{'content-type':'application/json','cache-control':'no-store'});
  res.end(JSON.stringify(valid?payload:{error:'isolated fixture route not found'}));
});
server.listen(5855,'127.0.0.1',()=>console.log('ISOLATED_BUSINESS_FIXTURE_READY 127.0.0.1:5855'));
