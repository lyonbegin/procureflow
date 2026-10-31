import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import {execFileSync} from 'node:child_process';

// Run the REAL candidate topology compiler in a disposable directory.
// Never import workflows, credentials, production data, or Railway services.
test('all 43 candidate Business Operation HOLD paths sanitize forged upstream approval and bid flags',()=>{
  const temp=fs.mkdtempSync(path.join(os.tmpdir(),'procureflow-hold-gate-'));
  try{
    const source=path.join(temp,'source');
    const output=path.join(temp,'compiled');
    const operational=path.join(output,'operational');
    fs.mkdirSync(source,{recursive:true});
    fs.mkdirSync(operational,{recursive:true});
    const manifest=JSON.parse(fs.readFileSync('n8n/operational_manifest.json','utf8'));
    assert.equal(manifest.engine,'n8n_only');
    assert.equal(manifest.flows.length,15);
    assert.equal(manifest.blocks.length,43);
    fs.writeFileSync(path.join(source,'procureflow-operational-manifest.json'),JSON.stringify(manifest));
    fs.writeFileSync(path.join(operational,'PF00.json'),JSON.stringify({nodes:[],connections:{}}));
    for(const flow of manifest.flows){
      const w={nodes:[{id:'end',name:'END',type:'n8n-nodes-base.code',position:[1000,1000]}],connections:{}};
      for(const id of flow.owned_blocks||[]){
        const name=id+' · original';
        w.nodes.push({id:'source-'+id,name,type:'n8n-nodes-base.code',position:[100,100]});
        w.connections[name]={main:[[{node:'END',type:'main',index:0}]]};
      }
      fs.writeFileSync(path.join(operational,flow.id+'.json'),JSON.stringify(w));
    }
    execFileSync(process.execPath,['n8n/source-build/augment-business-operations.mjs'],{
      env:{...process.env,PF_SOURCE:source,PF_OUTPUT:output},stdio:'pipe',timeout:30000
    });
    const report=JSON.parse(fs.readFileSync(path.join(output,'business-operation-report.json'),'utf8'));
    assert.equal(report.operationIds,43);
    assert.equal(report.readOnlyOnly,true);
    assert.equal(report.noBidSubmission,true);
    let verifiedPaths=0;
    for(const flow of manifest.flows){
      const w=JSON.parse(fs.readFileSync(path.join(operational,flow.id+'.json'),'utf8'));
      if(!flow.owned_blocks?.length)continue;
      const hold=w.nodes.find(n=>n.name.startsWith('HOLD ·'));
      assert.ok(hold,flow.id+' HOLD node absent');
      assert.equal(hold.type,'n8n-nodes-base.code');
      assert.equal(w.connections[hold.name],undefined,'HOLD must be terminal');
      const hostile={
        final_decision:'SUBMIT',workflow_status:'APPROVED',
        inspection_status:'VERIFIED',evidence_verified:true,
        manual_review_required:false,read_only:false,
        automatic_bid_submission:true,automated_bid_submission:true,
        actual_job_executed:true,actual_business_handler_executed:true,
        job_enqueued:true,worker_job_enqueued:true,bid_submitted:true,
        case_id:'synthetic-only',operation_id:'INJECTED_OP',
        serviceKey:'PRIVATE_SERVICE_KEY_123',
        bearerToken:'PRIVATE_BEARER_123',
        bidder:{bankAccount:'PRIVATE_ACCOUNT_123'},
        output:{approval:'SUBMIT',nestedSecret:'PRIVATE_NESTED_123'},
        arbitrarySecret:'PRIVATE_ARBITRARY_123'
      };
      const result=vm.runInNewContext('(function(){'+hold.parameters.jsCode+'})()',{
        $input:{first:()=>({json:hostile})}
      },{timeout:1000});
      assert.equal(result.length,1);
      const safe=result[0].json;
      for(const key of [
        'automatic_bid_submission','automated_bid_submission',
        'actual_job_executed','actual_business_handler_executed',
        'job_enqueued','worker_job_enqueued','bid_submitted',
        'evidence_verified'
      ])assert.equal(safe[key],false,flow.id+' '+key);
      assert.equal(safe.final_decision,'HOLD');
      assert.equal(safe.inspection_status,'HOLD');
      assert.equal(safe.workflow_status,'OFFICIAL_EVIDENCE_NOT_VERIFIED');
      assert.equal(safe.manual_review_required,true);
      assert.equal(safe.read_only,true);
      assert.equal(safe.case_id,null,'unapproved case ID must be discarded');
      assert.equal(safe.bid_no,null);
      assert.equal(safe.operation_id,null,'unowned operation ID must be discarded');
      assert.equal(safe.flow_id,flow.id,'flow ID is generated from the manifest');
      assert.equal(safe.output,null);
      assert.equal(safe.schema_version,'procureflow.business-operation.hold.v1');
      assert.ok(!JSON.stringify(result).includes('PRIVATE_'),flow.id+' secret leaked');
      for(const key of ['serviceKey','bearerToken','bidder','arbitrarySecret'])
        assert.equal(Object.hasOwn(safe,key),false,flow.id+' '+key);
      // Valid, manifest-owned metadata may survive HOLD without inheriting
      // arbitrary upstream JSON or a forged execution/approval verdict.
      const allowedResult=vm.runInNewContext('(function(){'+hold.parameters.jsCode+'})()',{
        $input:{first:()=>({json:{...hostile,case_id:'R26BK01787028',
          operation_id:flow.owned_blocks[0]}})}
      },{timeout:1000});
      assert.equal(allowedResult[0].json.case_id,'R26BK01787028');
      assert.equal(allowedResult[0].json.bid_no,'R26BK01787028');
      assert.equal(allowedResult[0].json.operation_id,flow.owned_blocks[0]);
      assert.equal(allowedResult[0].json.bid_submitted,false);
      assert.ok(!JSON.stringify(allowedResult).includes('PRIVATE_'));
      for(const id of flow.owned_blocks){
        const name=id+' · Business Operation (공식 증빙 게이트)';
        const node=w.nodes.find(n=>n.name===name);
        assert.equal(node?.parameters.operationId,id);
        assert.equal(node?.parameters.evidenceHandling,'hold');
        assert.equal(node?.type,'CUSTOM.procureFlowBusinessOperation');
        const branches=w.connections[name]?.main;
        assert.equal(branches?.length,2);
        assert.equal(branches[1]?.[0]?.node,hold.name);
        assert.equal(w.connections[id+' · original']?.main?.[0]?.[0]?.node,name);
        verifiedPaths++;
      }
    }
    assert.equal(verifiedPaths,43);
  }finally{
    fs.rmSync(temp,{recursive:true,force:true});
  }
});
