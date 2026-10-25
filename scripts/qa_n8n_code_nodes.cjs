/* Execute the actual n8n Code-node JavaScript in a constrained Node VM.
   No n8n server or external APIs are contacted. This validates that the
   exported stages are syntactically executable and propagate state/trace. */
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname,'..');
const manifest = JSON.parse(fs.readFileSync(path.join(root,'n8n/scenarios.json'),'utf8'));
function invoke(code, json) {
  const sandbox = Object.create(null);
  sandbox.$input = { first: () => ({ json }) };
  const fn = new vm.Script('(function(){\n'+code+'\n})()', {
    filename:'actual-n8n-code-node.js',
  });
  const output = fn.runInNewContext(sandbox,{timeout:3000});
  assert.ok(Array.isArray(output) && output.length === 1);
  assert.ok(output[0].json);
  return JSON.parse(JSON.stringify(output[0].json));
}
let executed = 0;
for (const entry of manifest.scenarios) {
  const graph = JSON.parse(fs.readFileSync(
      path.join(root,'n8n/workflows',entry.id+'.json'),'utf8'));
  const codeNodes = graph.nodes.filter(n=>n.type==='n8n-nodes-base.code');
  assert.equal(codeNodes.length,entry.steps.length+3);
  let payload = null;
  for (let i=0;i<codeNodes.length-1;i++){
    payload=invoke(codeNodes[i].parameters.jsCode,payload);
    executed++;
    if(i===0) {
      assert.equal(payload.scenario_id,entry.id);
      assert.equal(payload.case_id,'DEMO_ONLY');
      assert.equal(payload.simulation_only,true);
    } else if(i<=entry.steps.length) {
      const source=entry.steps[i-1];
      const record=payload.trace.at(-1);
      assert.equal(record.event,source.event);
      assert.equal(record.flow,source.flow);
      assert.equal(record.index,source.index);
      assert.deepEqual(record.output,source.patch);
      assert.deepEqual(record.recipients,source.recipients);
    }
  }
  assert.equal(payload.trace.length,entry.steps.length,entry.id);
  assert.equal(payload.verdict,entry.expected,entry.id);
  assert.equal(payload.passed,true,entry.id);
  assert.equal(payload.bid_submitted,false);
  assert.equal(payload.simulation_only,true);
  const finish=invoke(codeNodes.at(-1).parameters.jsCode,
                      {passed:true,scenario_id:entry.id,verdict:entry.expected});
  assert.equal(finish.workflow_status,'SIMULATED_PASS');
  // If the FastAPI comparison rejects an execution, n8n's terminal step must fail.
  assert.throws(()=>invoke(codeNodes.at(-1).parameters.jsCode,{passed:false}),
                /scenario QA failed/i);
}
console.log('N8N_NATIVE_NODE_JS_10_SCENARIOS_PASSED scenario_count=10 code_nodes_executed='+executed);
