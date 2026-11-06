import {readFileSync,writeFileSync} from 'node:fs';
const path=process.argv[2];
if(!path)throw Error('catalog path required');
let source=readFileSync(path,'utf8');
const mark="export const PROCURE_WORKFLOWS=Object.freeze([\n";
if(!source.includes(mark)||!source.includes("PROCURE_WORKFLOWS.length!==29"))
  throw Error('unexpected pinned shared studio catalog');
source=source.replace(mark,mark+
"  ['operations/PF00-public-nine-real.json','실제 공고 · 9단계 원본 증빙 조회'],\n"+
"  ['operations/PF01-stage1-dataflow.json','실제 공고 · N01/N02 식별·조건 분기'],\n");
if(!source.includes("size!==29")||!source.includes("must contain 29 unique"))
  throw Error('unexpected shared studio uniqueness guard');
source=source.replace("PROCURE_WORKFLOWS.length!==29","PROCURE_WORKFLOWS.length!==31");
source=source.replace("size!==29","size!==31");
source=source.replace("must contain 29 unique","must contain 31 unique");
if(!source.includes("length!==31")||!source.includes("size!==31")||!source.includes("must contain 31 unique"))
  throw Error('failed to patch procurement workflow catalog counts');
writeFileSync(path,source);
console.log('PROCUREFLOW_REAL_WORKFLOW_SELECTOR_REGISTERED=31');
const appPath=process.argv[3];
if(!appPath)throw Error('App.vue path required for project-safe N01 input defaults');
let app=readFileSync(appPath,'utf8');
const from="node01InputJson.value=JSON.stringify({ui_selection:node01Mode(),requested_detail_limit:1},null,2);";
const to="node01InputJson.value=JSON.stringify(IS_PROCUREMENT?(stockOriginal.value?.meta?.studioDefaultInput||{}):{ui_selection:node01Mode(),requested_detail_limit:1},null,2);";
if(!app.includes(from))throw Error("unexpected pinned shared App N01 defaults");
app=app.replace(from,to);
// Add a one-click live nine-stage run to the pinned common editor only.
const liveInsert="const stockFlow=ref(stockWorkflows[0][0]);";
if(app.split(liveInsert).length!==2)throw Error("PINNED_SHARED_STOCKFLOW_LOCATION_CHANGED");
const liveLogic="\nconst liveNineRun=ref(null),liveNineRunning=ref(false),liveNineError=ref('');\nasync function liveNineRequest(route,options={}){\n  const response=await fetch('/api/procurement/public9/'+route,\n    {credentials:'same-origin',cache:'no-store',...options});\n  const data=await response.json().catch(()=>({error:'JSON_RESPONSE_REQUIRED'}));\n  if(!response.ok)throw Error(data.error||'LIVE_G2B_HTTP_'+response.status);\n  return data;\n}\nasync function executeLiveNine(){\n  if(liveNineRunning.value||stockFlow.value!=='operations/PF00-public-nine-real.json')return;\n  liveNineRunning.value=true;liveNineError.value='';\n  try{\n    await liveNineRequest('live-run');\n    let data=await liveNineRequest('run-all',{method:'POST',\n      headers:{'Content-Type':'application/json'},\n      body:JSON.stringify({bid_no:'R26BK01787028',detail10:'8111159901'})});\n    liveNineRun.value=data;\n    for(let trial=0;trial<180&&data.status==='running';trial++){\n      await new Promise(ok=>setTimeout(ok,1500));\n      data=await liveNineRequest('live-run');\n      liveNineRun.value=data;\n      if(stockFlow.value==='operations/PF00-public-nine-real.json'){\n        const statusById=new Map((data.steps||[]).map(step=>['public9-'+step.node.slice(1),\n          step.status==='verified'?'success':step.status==='source_error'?'error':'ready']));\n        if(data.active_node)statusById.set('public9-'+data.active_node.slice(1),'running');\n        nodes.value=nodes.value.map(n=>({...n,data:{...n.data,\n          state:statusById.get(n.id)||'idle',stateSource:'live_official_test'}}));\n      }\n    }\n    if(data.status==='running')liveNineError.value='실제 수집 진행 상태는 관리센터에서 확인할 수 있습니다.';\n  }catch(e){liveNineError.value=e.message||String(e);}\n  finally{liveNineRunning.value=false;}\n}\n";
app=app.replace(liveInsert,liveInsert+liveLogic);
const controls='<button class="primary-btn" @click="saveLocal">';
if(!app.includes(controls))throw Error("PINNED_EDITOR_TOOLBAR_MARKER_CHANGED");
const liveButton="<button v-if=\"IS_PROCUREMENT && stockFlow==='operations/PF00-public-nine-real.json'\" class=\"primary-btn\" data-testid=\"live-nine-run-all\" :disabled=\"liveNineRunning\" @click=\"executeLiveNine\">▶ {{liveNineRunning?'실제 9단계 수집 중':'9개 전체 순차 실행 · 실수집'}}</button>\n            ";
app=app.replace(controls,liveButton+controls);
const info='<div class="canvas-info">';
if(!app.includes(info))throw Error("PINNED_EDITOR_INFO_MARKER_CHANGED");
const liveInfo="<section v-if=\"IS_PROCUREMENT && stockFlow==='operations/PF00-public-nine-real.json'\" data-testid=\"live-nine-progress\" style=\"padding:10px;border-bottom:1px solid #ccd5e3\">\n  <b>실제 G2B 9단계 실행</b> · {{liveNineRun?.status||'대기'}} · {{liveNineRun?.completed_steps||0}}/9 <b v-if=\"liveNineRun?.active_node\"> · 현재 {{liveNineRun.active_node}}: {{liveNineRun.active_title}} 수집 중</b> · DB/Worker/Chromium 사용 안 함\n  <p v-if=\"liveNineError\" style=\"color:#b23443\">{{liveNineError}}</p>\n  <div v-for=\"step in (liveNineRun?.steps||[])\" :key=\"step.node\">\n   <details><summary>{{step.node}} · {{step.title}} · {{step.status}}</summary>\n   <pre style=\"white-space:pre-wrap;overflow-wrap:anywhere\">INPUT {{JSON.stringify(step.input,null,2)}}\nOUTPUT {{JSON.stringify(step.output,null,2)}}</pre></details>\n  </div>\n </section>\n          ";
app=app.replace(info,liveInfo+info);
writeFileSync(appPath,app);
console.log('PROCUREFLOW_LIVE_NINE_BUTTON_PATCHED_SHARED_EDITOR');
