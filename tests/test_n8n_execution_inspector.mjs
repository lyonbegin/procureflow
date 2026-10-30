import assert from 'node:assert/strict';
import {inspectN8nExecution} from '../n8n/studio-bridge/inspect-n8n-execution.mjs';
const mock=async(url,options)=>{
 assert.equal(options.method,'GET');
 assert.equal(options.headers['X-N8N-API-KEY'],'unit-test-only');
 assert(url.endsWith('/api/v1/executions/123?includeData=true'));
 return {ok:true,json:async()=>({id:'123',status:'success',finished:true,data:{resultData:{runData:{
  Start:[{executionTime:5}],Analyze:[{executionTime:13}],End:[{executionTime:2,error:{message:'mock'}}]
 }}}})};
};
const r=await inspectN8nExecution({baseUrl:'https://existing.example.invalid',apiKey:'unit-test-only',executionId:'123',transport:mock});
assert.equal(r.executionId,'123');
assert.equal(r.nodes.length,3);
assert.equal(r.nodes[2].status,'error');
assert.equal(r.mode,'existing_official_n8n_read_only');
assert(!JSON.stringify(r).includes('unit-test-only'));
await assert.rejects(inspectN8nExecution({baseUrl:'https://existing.example.invalid',executionId:'123',transport:mock}),/key/);
await assert.rejects(inspectN8nExecution({baseUrl:'https://existing.example.invalid',apiKey:'x',executionId:'../../foo',transport:mock}),/Invalid/);
console.log('OFFLINE_N8N_EXECUTION_READ_ONLY_STATUS_PASS');
