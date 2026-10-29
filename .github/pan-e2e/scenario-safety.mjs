/**
 * Pure, offline safety boundary for S01–S10 official n8n Chrome fixtures.
 * No network access or n8n runtime is used by this module.
 * Production QA HTTP nodes are replaced with local Code assertions BEFORE import.
 */
const ALLOWED_TYPES=new Set([
  'n8n-nodes-base.manualTrigger','n8n-nodes-base.code','n8n-nodes-base.httpRequest'
]);
// Reject code that can reach arbitrary APIs or load dynamic modules in the
// disposable n8n process. A literal "quote_required" is not a require() call.
const SIDE_EFFECTFUL_CODE=/\b(?:fetch|import|require|eval|Function|WebSocket|XMLHttpRequest)\s*\(|\b(?:globalThis|process)\s*(?:\.|\[)|\$(?:http|request|helpers)\b/;
const assert=(condition,message)=>{if(!condition)throw Error(message);};

export function makeSafeScenario(original,id){
  assert(/^S(?:0[1-9]|10)$/.test(id),'Invalid synthetic scenario ID');
  assert(original&&typeof original==='object'&&!Array.isArray(original),'Invalid scenario JSON');
  assert(original.active===false,id+': original fixture must remain inactive');
  assert(Array.isArray(original.nodes)&&original.nodes.length>0,id+': missing native nodes');
  const fixture=structuredClone(original);
  const httpNodes=fixture.nodes.filter(n=>n.type==='n8n-nodes-base.httpRequest');
  assert(httpNodes.length===1,id+': exactly one original QA node required');
  const names=new Set(),nodeIds=new Set();
  for(const n of fixture.nodes){
    assert(n&&ALLOWED_TYPES.has(n.type),id+': unsupported node '+n?.type);
    assert(typeof n.id==='string'&&n.id&&!nodeIds.has(n.id),id+': invalid/duplicate node ID');
    assert(typeof n.name==='string'&&n.name&&!names.has(n.name),id+': invalid/duplicate node name');
    assert(!Object.hasOwn(n,'credentials'),id+': credentials prohibited in synthetic fixture');
    nodeIds.add(n.id);names.add(n.name);
    if(n.type==='n8n-nodes-base.httpRequest'){
      assert(n.parameters?.method==='POST'&&
        n.parameters.url==='https://procureflow-api-production.up.railway.app/api/n8n/scenarios/'+id+'/verify',
        id+': unapproved external HTTP source');
      // Replace the ONLY original production QA endpoint with a local,
      // deterministic assertion. No HTTP Request node survives this function.
      n.type='n8n-nodes-base.code';
      n.typeVersion=2;
      n.parameters={mode:'runOnceForAllItems',jsCode:
        "const v=$input.first().json;"+
        "if(v.scenario_id!=="+JSON.stringify(id)+"||v.case_id!=='DEMO_ONLY'||v.simulation_only!==true||v.bid_submitted!==false||v.verdict!==v.expected||v.passed!==true) throw new Error('Scenario mocked QA assertion failed');"+
        "return [{json:{...v,qa_local_only:true}}];"};
      n.notes='ISOLATED CHROME TEST ONLY — local QA assertion; not remote G2B verification';
    }else if(n.type==='n8n-nodes-base.code'){
      assert(typeof n.parameters?.jsCode==='string'&&
        !SIDE_EFFECTFUL_CODE.test(n.parameters.jsCode),
        id+': side-effectful or dynamic Code node '+n.name);
    }
  }
  assert(!fixture.nodes.some(n=>n.type==='n8n-nodes-base.httpRequest'),
    id+': HTTP node not fully disabled');
  delete fixture.id;
  delete fixture.active;
  delete fixture.staticData;
  delete fixture.meta;
  fixture.tags=[];
  fixture.name='[ISOLATED CHROME '+id+'] '+fixture.name;
  return fixture;
}
