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
// Add the same one-click, no-database real G2B test to the SHARED editor
// without modifying the common upstream investment repo.
const liveInsert="const stockFlow=ref(stockWorkflows[0][0]);";
if(app.split(liveInsert).length!==2)throw Error("PINNED_SHARED_STOCKFLOW_LOCATION_CHANGED");
app=app.replace(liveInsert,liveInsert+String.raw\`
const liveNineRun=ref(null),liveNineRunning=ref(false),liveNineError=ref('');
async function liveNineRequest(route,options={}){
  const response=await fetch('/api/procurement/public9/'+route,
    {credentials:'same-origin',cache:'no-store',...options});
  const data=await response.json().catch(()=>({error:'JSON_RESPONSE_REQUIRED'}));
  if(!response.ok)throw Error(data.error||'LIVE_G2B_HTTP_'+response.status);
  return data;
}
async function executeLiveNine(){
  if(liveNineRunning.value||stockFlow.value!=='operations/PF00-public-nine-real.json')return;
  liveNineRunning.value=true;liveNineError.value='';
  try{
    await liveNineRequest('live-run');
    let data=await liveNineRequest('run-all',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({bid_no:'R26BK01787028',detail10:'8111159901'})});
    liveNineRun.value=data;
    for(let trial=0;trial<180&&data.status==='running';trial++){
      await new Promise(ok=>setTimeout(ok,1500));
      data=await liveNineRequest('live-run');
      liveNineRun.value=data;
      if(stockFlow.value==='operations/PF00-public-nine-real.json'){
        const statusById=new Map((data.steps||[]).map(step=>['public9-'+step.node.slice(1),
          step.status==='verified'?'success':step.status==='source_error'?'error':'ready']));
        nodes.value=nodes.value.map(n=>({...n,data:{...n.data,
          state:statusById.get(n.id)||'idle',stateSource:'live_official_test'}}));
      }
    }
    if(data.status==='running')liveNineError.value='실제 수집 진행 상태는 관리센터에서 확인할 수 있습니다.';
  }catch(e){liveNineError.value=e.message||String(e);}
  finally{liveNineRunning.value=false;}
}
\`);
const controls='<button class="primary-btn" @click="saveLocal">';
if(!app.includes(controls))throw Error("PINNED_EDITOR_TOOLBAR_MARKER_CHANGED");
app=app.replace(controls,
 '<button v-if="IS_PROCUREMENT && stockFlow===\\'operations/PF00-public-nine-real.json\\'"'+
 ' class="primary-btn" data-testid="live-nine-run-all" :disabled="liveNineRunning"'+
 ' @click="executeLiveNine">▶ {{liveNineRunning?\\'실제 9단계 수집 중\\':\\'9개 전체 순차 실행 · 실수집\\'}}</button>\\n            '+controls);
const info='<div class="canvas-info">';
if(!app.includes(info))throw Error("PINNED_EDITOR_INFO_MARKER_CHANGED");
app=app.replace(info,
 '<section v-if="IS_PROCUREMENT && stockFlow===\\'operations/PF00-public-nine-real.json\\'"'+
 ' data-testid="live-nine-progress" style="padding:10px;border-bottom:1px solid #ccd5e3">'+
 '<b>실제 G2B 9단계 실행</b> · {{liveNineRun?.status||\\'대기\\'}}'+
 ' · {{liveNineRun?.completed_steps||0}}/9 · DB/Worker/Chromium 사용 안 함'+
 '<p v-if="liveNineError" style="color:#b23443">{{liveNineError}}</p>'+
 '<div v-for="step in (liveNineRun?.steps||[])" :key="step.node">'+
 '<details><summary>{{step.node}} · {{step.title}} · {{step.status}}</summary>'+
 '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">INPUT {{JSON.stringify(step.input,null,2)}}\\nOUTPUT {{JSON.stringify(step.output,null,2)}}</pre></details></div>'+
 '</section>\\n          '+info);
writeFileSync(appPath,app);
console.log('PROCUREFLOW_LIVE_NINE_BUTTON_PATCHED_SHARED_EDITOR');
