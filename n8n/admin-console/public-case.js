/* Public-only selected tender command center. B/C modules are untouched.
 * This uses ORIGINAL g2b_feature_registry.py 104-function acceptance rules and
 * ORIGINAL n8n/operational_manifest.json 43 blocks exported at Docker build.
 * Only synthetic data passes through shared Studio Python node/test/SQLite APIs.
 * There are no G2B, Work24, bid, or external browser fetches in this module.
 */
(function(){
'use strict';
const WF="operations/A01-public-win-strategy.json";
const ROOT="/api/studio/workflows/"+WF;
const GROUPS=[
 ["notice","공고 발견·식별",1,16],
 ["detail","공고 원본·첨부·RFP",17,32],
 ["history","개찰·투찰·낙찰 이력",33,48],
 ["matching","정확한 10자리 종목·기관·경쟁",49,60],
 ["eligibility","회사 자격·공급업체·인력",61,76],
 ["pricing","원가·수주전략·제안서",77,94],
 ["operations","검증·작업이력·입찰 직전",95,104]
];
const caseState={
 catalog:null, workflow:null, run:null, history:null, rows:[],
 selectedNode:null, busy:false, cancel:false, loading:false, loadError:null, stage:'selected',
 latestRuns:[], readiness:null
};
const escapeHtml=x=>String(x===undefined||x===null?'':x).replace(/[&<>"']/g,v=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[v]));
const pretty=x=>JSON.stringify(x===undefined?null:x,null,2);
const badge=(s,css='')=>'<span class="badge '+css+'">'+escapeHtml(s)+'</span>';
const action=(key,title,css='small',disabled=false,attrs='')=>'<button type="button" class="btn '+css+'" data-public-action="'+key+'" '+(disabled?'disabled':'')+' '+attrs+'>'+escapeHtml(title)+'</button>';
const card=(title,body,cls='')=>'<section class="panel '+cls+'"><h3>'+title+'</h3>'+body+'</section>';
const stat=(label,value,small)=>'<div class="metric"><div class="legend">'+escapeHtml(label)+'</div><div class="num">'+escapeHtml(value)+'</div><small>'+escapeHtml(small)+'</small></div>';
const info=(msg,warn=false)=>'<div class="notice '+(warn?'warn':'')+'">'+msg+'</div>';
const selectCase=()=>caseState.catalog?.case||{bid_no:"R26BK01787028",bid_ord:"000",detail10:"8111159901",source:"fictional_test_fixture"};
const progress=()=>{
 const r=caseState.run,n=caseState.workflow?.nodes?.length||43,count=r?.records?.length||0;
 const done=count===n&&(r?.status==="COMPLETE");
 return '<div class="runline">'+badge(r?.status||'실행 전',done?'ok':'warn')+
 '<span class="muted smalltxt">원본 업무 블록 '+count+'/'+n+' · 기능 '+(r?.records?.at(-1)?.output_json?Object.keys(r.records.at(-1).output_json.feature_results||{}).length:0)+'/104</span>'+
 '<span class="muted smalltxt">'+escapeHtml(r?.workflowRunId||'Run ID 없음')+'</span></div>'+
 '<div class="progress" style="margin:12px 0"><div class="bar" style="width:'+Math.min(100,Math.round(count/n*100))+'%"></div></div>';
};
async function getJSON(url,options){
 const r=await fetch(url,{cache:'no-store',credentials:'same-origin',...options});
 const obj=await r.json();
 if(!r.ok)throw Error(obj.error||obj.detail||('HTTP '+r.status));
 return obj;
}
function changed(){window.dispatchEvent(new Event('public-case-changed'));}
function viewJson(value,title){
 return '<details><summary>'+escapeHtml(title||'원본 JSON 확인')+'</summary><pre class="log">'+escapeHtml(pretty(value))+'</pre></details>';
}
function proposalView(result){
 if(!result)return '<div class="empty">이 입찰에 대한 가격·수주전략·제안서 결과가 아직 없습니다.</div>';
 const results=result.results||{},p=results.P07||{},offer=results.R01||{},cost=results.P03||{},
 hist=results.H11||{},elig=results.Q05||{},audit=results.O04||{};
 return '<div class="metric-grid">'+
 stat('모의 낙찰 비교 표본',hist.coverage?.mock_award_rows||0,'실제 10년 개찰 전수 검증 0')+
 stat('모의 원가',cost.total_cost_krw?cost.total_cost_krw.toLocaleString('ko-KR')+'원':'미산출','실제 견적 증빙 없음')+
 stat('모의 가격전략',p.selected?.name||'미결정','투찰가격 승인 아님')+
 stat('최종 공식 준비상태',audit.decision||'HOLD','실제 입찰참가 불가')+'</div>'+
 '<div class="panels">'+card('① 과거 낙찰·경쟁 분석', 
 '<p>실제 원본의 정확한 10자리 종목·기관·참가업체·투찰결과가 모두 확인되어야 공식 전략 분석이 가능합니다.</p>'+
 '<div class="table-wrap"><table><tbody>'+
 [['시험 세부종목',result.detail10],['모의 121개월',hist.coverage?.mock_replay_complete?'모의 처리 완료':'미완료'],
 ['공식 수집·검증 기간',hist.coverage?.official_windows_verified||0],
 ['모의 평균낙찰률',results.P04?.synthetic_mean_award_ratio===undefined?'미산출':(100*results.P04.synthetic_mean_award_ratio).toFixed(2)+'%'],
 ['실제 경쟁업체 검증',results.H10?.real_competitor_identified?'있음':'없음']].map(([k,v])=>'<tr><th>'+escapeHtml(k)+'</th><td>'+escapeHtml(v)+'</td></tr>').join('')+
 '</tbody></table></div>')+
 card('② 자격·공급·원가 심사','<div class="stack">'+
 ['회사 참가자격: '+(elig.status||'미확인'),
 '원본 견적 확인: '+(results.S04?.real_verified_quote_count||0)+'건',
 '실제 낙찰가격 산식: '+(results.P05?.official_price_formula_verified?'검증':'미검증'),
 '가상 총원가: '+(cost.total_cost_krw?.toLocaleString('ko-KR')||'미산출')+'원'].map(x=>'<div class="item">'+escapeHtml(x)+'</div>').join('')+'</div>')+'</div>'+
 '<div class="panels">'+
 card('③ 수주전략 결정','<h4>후보별 원가·마진</h4>'+
 (results.P06?.options?.length?'<table><thead><tr><th>전략</th><th>가상가격</th><th>원가</th><th>마진율</th></tr></thead><tbody>'+
 results.P06.options.map(o=>'<tr><td>'+escapeHtml(o.name)+'</td><td>'+o.price_krw.toLocaleString()+'</td>'+
 '<td>'+o.cost_krw.toLocaleString()+'</td><td>'+o.margin_pct+'%</td></tr>').join('')+
 '</tbody></table>':'<div class="empty">가격 시나리오 미산출</div>')+
 '<p class="muted smalltxt">선택 근거: '+escapeHtml(p.strategy_reason||'아직 없음')+'</p>'+
 info('과거 낙찰 데이터만으로 과거 기술제안서나 기술평가 결과를 알 수 없습니다. 또한 현재 가격은 실제 투찰 가격이 아닙니다.',true))+
 card('④ 제안서·참가서류 준비','<p>선택 전략: <b>'+escapeHtml(offer.strategy||'미선택')+'</b></p><p>강조 내용: <b>'+escapeHtml(offer.emphasis||'미산출')+'</b></p>'+
 '<div class="stack">'+(offer.sections||[]).map(s=>'<div class="item"><b>'+escapeHtml(s)+'</b></div>').join('')+'</div>'+
 '<h4>미확인 선행조건</h4><div class="stack">'+(audit.missing_verification||[]).map(s=>'<div class="item">'+escapeHtml(s)+'</div>').join('')+'</div>')+
 '</div>'+info('입찰참가 직전에는 공식 공고·문서·10년 낙찰 데이터·회사 증빙·원가·제출양식을 실제 검증해야 합니다. 모의 완료를 READY로 바꾸지 않습니다.',true);
}
function blockGroups(){
 const manifest=caseState.catalog?.manifest_blocks||[];
 const featureIndex=caseState.run?.records?.at(-1)?.output_json?.feature_results||{};
 return '<div class="table-wrap"><table><thead><tr><th>업무영역</th><th>기능번호</th><th>모의 실행</th><th>공식 원본 검증</th></tr></thead><tbody>'+
 GROUPS.map(([key,name,from,to])=>{
 const all=Array.from({length:to-from+1},(_,i)=>from+i);
 const covered=all.filter(no=>featureIndex[String(no)]?.test_status==="MOCK_EXECUTED").length;
 return '<tr><td>'+escapeHtml(name)+'</td><td>'+from+'~'+to+'</td>'+
 '<td>'+badge(covered+'/'+all.length,'')+'</td><td>'+badge('공식 검증 없음','warn')+'</td></tr>';
 }).join('')+'</tbody></table></div>'+
 '<p class="muted smalltxt">업무 노드 '+manifest.length+'개 · 실제 기존 manifest의 기능번호·증빙 게이트를 사용</p>';
}
function runControls(){
 const r=caseState.run,completed=r&&r.records.length===43,disabled=caseState.busy;
 return '<div class="actions">'+
 action('start','① 선택 입찰 1건 실행 시작','primary',disabled)+
 action('next','② 다음 원본 업무 블록 실행','small',disabled||!r||completed)+
 action('all','▶ PF 전체 43블록·104기능 모의 검증','green',disabled)+
 action('stop','■ 중지','stop',!disabled)+
 action('reset','기록 초기화','outline',disabled)+
 '<a class="btn small" href="/?workflow='+encodeURIComponent(WF)+'" target="_blank" rel="noopener">↗ 실제 43개 노드 캔버스 열기</a></div>';
}
function historyRows(){
 const rows=caseState.latestRuns||[];
 if(!rows.length)return '<div class="empty">현재 브라우저에 저장된 공공입찰 테스트 이력이 없습니다.</div>';
 return '<div class="table-wrap"><table><thead><tr><th>시각</th><th>발주</th><th>실행 노드</th><th>판정</th><th>증빙</th></tr></thead><tbody>'+
 rows.map(row=>'<tr><td>'+escapeHtml(row.last_at||'—')+'</td><td>R26BK01787028 / 000</td>'+
 '<td>'+escapeHtml(row.completed_nodes)+'/43</td><td>'+badge(row.decision||row.last_status,row.decision?'warn':'')+'</td>'+
 '<td>'+action('history','Run 원본 확인','small',false,'data-run="'+escapeHtml(row.workflow_run_id)+'"')+'</td></tr>').join('')+
 '</tbody></table></div>';
}
function selector(){
 const c=selectCase();
 return '<section class="panel"><h3>① 현재 선택된 입찰공고</h3>'+
 '<div class="metric-grid">'+stat('공고번호',c.bid_no,'차수 '+c.bid_ord)+
 stat('공식 10자리 세부품명',c.detail10,'분류 확인은 가상 상태')+
 stat('전체 업무 기능','104','기존 Python 기능 계약')+
 stat('업무 원본 블록','43','PF00~PF15 원본 명세')+'</div>'+
 '<div class="item"><b>'+escapeHtml(c.title||'선택 공고')+'</b>'+
 '<p>데이터 출처: '+escapeHtml(c.source)+' · 이 테스트는 이전에 선택했던 한 건의 번호를 재사용하며 현재 공식 공고 내용을 수집하지 않습니다.</p></div>'+
 '<div class="actions">'+action('select','이 공고 한 건으로 작업 선택','primary')+
 '<a class="btn small" href="/?workflow='+encodeURIComponent(WF)+'" target="_blank" rel="noopener">원본 43블록 캔버스 ↗</a></div>'+
 info('본 공고번호는 기존 프로젝트의 선택 사례입니다. 회사·발주기관·금액·낙찰 결과는 가상 값이며 실제 입찰 완료 조건을 충족시키지 않습니다.',true)+'</section>';
}
function renderOverview(){
 return '<section class="hero"><div class="kicker">PUBLIC PROCUREMENT · SINGLE TENDER COMMAND</div>'+
 '<h2>입찰 한 건을 선택해 104개 업무를 끝까지 준비합니다</h2>'+
 '<p>주식의 전략 1개와 동일하게 공공입찰 1건을 고정합니다. 원본·첨부 → 정확한 10자리 세부품명 10년 개찰·낙찰 → 경쟁업체 → 자격·공급·인력 → 가격·수주전략 → 제안서 → 독립 감사·사람의 입찰참가 결정을 진행합니다.</p>'+
 '<div class="actions">'+action('start','▶ 선택 입찰 모의 처리 시작','primary')+
 '<button data-page="public" class="btn small">입찰 한 건 상세 관제</button>'+
 '<button data-page="features" class="btn small">104개 기능별 검증</button></div></section>'+
 selector()+'<div class="metric-grid">'+
 stat('현재 발주','1건','다른 공고로 자동 변경 안 함')+
 stat('원래 43개 업무 노드',caseState.workflow?.nodes?.length||'43','기존 manifest 기반')+
 stat('모의 검증된 기능',Object.keys(caseState.run?.records?.at(-1)?.output_json?.feature_results||{}).length+'/104','공식 검증과 무관')+
 stat('최종 준비 판정',caseState.run?.records?.at(-1)?.output_json?.results?.O04?.decision||'HOLD','투찰 버튼 클릭 금지')+
 '</div>'+
 '<div class="panels">'+card('② 원래 7개 업무단계의 진행 상태',blockGroups())+
 card('③ 사용자 입찰 준비 산출물',proposalView(caseState.run?.records?.at(-1)?.output_json))+'</div>'+
 card('④ 이 입찰 1건의 실제 SQLite 모의 기록',historyRows());
}
function renderPublic(){
 return '<section class="hero"><div class="kicker">PUBLIC TENDER / 104 STEPS</div><h2>입찰 한 건의 전체 실행·수주전략·최종 서류</h2>'+
 '<p>기존 PF00~PF15, 43개 블록, 104개 기능을 그대로 적용합니다. 이번 테스트에서는 외부 크롤링·운영 n8n 실행을 차단하고 같은 업무 계약을 가상 원본으로 검증합니다.</p></section>'+
 selector()+card('② 전체 처리 및 진행 상황',progress()+runControls()+blockGroups())+
 card('③ 과거 낙찰데이터 → 가격전략 → 제안서',proposalView(caseState.run?.records?.at(-1)?.output_json))+
 card('④ 검증·감사·중단 이유',historyRows());
}
function renderTests(){
 const r=caseState.run,nodes=caseState.workflow?.nodes||[];
 const chosen=r?.records?.find(x=>x.node_id===caseState.selectedNode)||r?.records?.at(-1);
 return '<section class="hero"><div class="kicker">SELECTED TENDER TEST LAB</div>'+
 '<h2>같은 입찰 건의 43개 원본 노드·104개 기능을 단계별로 검사</h2>'+
 '<p>원래 기능별 증빙 요건을 읽고 각 업무 블록의 실제 Python 테스트 계산을 호출합니다. 중간 단계 입력·출력·SQLite Run ID를 확인할 수 있습니다. 실제 공식 데이터 수집은 하지 않습니다.</p></section>'+
 card('선택한 입찰과 실행 조작',progress()+runControls()+
 '<p class="muted smalltxt">선택 공고 R26BK01787028 / 000 · 정확한 10자리 분류 8111159901 · 공식 원본 검증 없음</p>')+
 '<div class="panels">'+card('43개 업무 노드의 실제 테스트 순서',
 nodes.length?'<div class="timeline">'+nodes.map((n,i)=>{let ok=r?.records?.find(x=>x.node_id===n.id);
 return '<button class="step '+(ok?'done':'')+(caseState.selectedNode===n.id?' selected':'')+'" data-public-action="inspect" data-node="'+escapeHtml(n.id)+'">'+
 '<strong>'+escapeHtml(n.name)+'</strong><small>'+escapeHtml(n.id)+' · '+escapeHtml(ok?'Python MOCK 성공 '+ok.duration_ms+'ms':'테스트 대기')+'</small></button>';
 }).join('')+'</div>':'<div class="loading">43개 원본 업무 노드 목록 불러오는 중…</div>')+
 '<p class="muted smalltxt">이 테스트의 직렬 연결은 순차 입력 전달용입니다. 운영 n8n의 실제 PF 업무 DAG를 대체하지 않습니다.</p>'+
 card('선택한 노드 입력·출력·증빙',chosen?'<h4>'+escapeHtml(chosen.node_id)+' · '+escapeHtml(chosen.status)+'</h4>'+
 '<div class="muted smalltxt">run_id '+escapeHtml(chosen.run_id)+' · '+escapeHtml(chosen.duration_ms)+'ms</div>'+
 '<h4>INPUT</h4><pre class="log">'+escapeHtml(pretty(chosen.input_json))+'</pre>'+
 '<h4>OUTPUT · 104개 원본 업무계약</h4><pre class="log">'+escapeHtml(pretty(chosen.output_json?.last_block))+'</pre>'+
 '<h4>오류</h4><pre class="log">'+escapeHtml(chosen.error||'없음')+'</pre>':
 '<div class="empty">선택 입찰 실행 후 노드를 클릭하면 입력·출력 증빙이 표시됩니다.</div>')+
 '</div>'+
 card('현재 실행 결과 및 입찰 준비 판단',proposalView(r?.records?.at(-1)?.output_json));
}
function renderFeatures(){
 const c=caseState.catalog,records=c?.features||[],
 checks=caseState.run?.records?.at(-1)?.output_json?.feature_results||{};
 return '<section class="hero"><div class="kicker">ORIGINAL 104 BUSINESS FUNCTIONS</div>'+
 '<h2>선택된 입찰의 104개 기능별 처리·증빙 상태</h2>'+
 '<p>기능별 명칭·증빙 요구조건을 원래 g2b_feature_registry.py에서 빌드 시 직접 추출했습니다. 모의 노드 성공은 실제 입찰업무 검증 완료가 아닙니다.</p></section>'+
 '<div class="metric-grid">'+stat('원본 기능',records.length||'104','기존 2026-10-28 기능 계약')+
 stat('모의 실행',Object.keys(checks).length+'/104','노드 호출 결과')+
 stat('공식 10년 증빙',0,'수집하지 않음')+
 stat('입찰참가 준비','HOLD','원본·자격·가격 검증 미충족')+'</div>'+
 card('7개 업무분야 완료 현황',blockGroups())+
 card('104개 기능별 실제 계약 · 검증 요건','<div class="table-wrap"><table><thead><tr><th>번호</th><th>기능명</th><th>담당 블록</th><th>모의 처리</th><th>공식 근거</th></tr></thead><tbody>'+
 records.map(item=>{let hit=checks[String(item.number)];
 return '<tr><td>F'+String(item.number).padStart(3,'0')+'</td><td><strong>'+escapeHtml(item.label)+'</strong>'+
 '<div class="muted smalltxt">필요 증빙: '+escapeHtml((item.required_evidence||[]).join(', '))+'</div></td>'+
 '<td>'+escapeHtml(item.block_id)+'</td><td>'+badge(hit?'MOCK 실행':'미실행',hit?'ok':'warn')+'</td>'+
 '<td>'+badge('공식 미검증','warn')+'</td></tr>';
 }).join('')+'</tbody></table></div>')+
 info('공식 입찰 준비 완료 여부는 기존 g2b_case_engine.py의 독립 증빙 판정이 기준입니다. 테스트용 입력값과 기능의 구현·증빙 완료를 혼동하지 않습니다.',true);
}
function renderStrategy(){
 return '<section class="hero"><div class="kicker">AWARD DATA → WIN STRATEGY → PROPOSAL</div>'+
 '<h2>낙찰데이터가 실제 입찰전략과 제안서를 바꾸는 과정</h2>'+
 '<p>10년의 실제 투찰·낙찰 기록, RFP 평가기준, 자격, 공급업체 견적, 원가가 한 입찰 건에 결합되어야 합니다. 모의 자료로 대안을 계산하되 공식 결과로 과장하지 않습니다.</p></section>'+
 selector()+card('기존 업무 104개 기반 전략·가격·제안서',proposalView(caseState.run?.records?.at(-1)?.output_json));
}
function renderAudit(){
 let h=caseState.history,r=caseState.run;
 return '<section class="hero"><div class="kicker">TENDER CASE PROVENANCE</div><h2>입찰 한 건의 노드 실행·증빙·최종 HOLD 이유</h2>'+
 '<p>모의 실행 기록은 Studio SQLite에 브라우저 세션별 저장됩니다. 실제 원본 증빙과 업무 PostgreSQL은 별도이며 현재 입찰참가 제출은 차단되어 있습니다.</p></section>'+
 card('발주별 Run ID·실행 기록',progress()+historyRows())+
 card('선택 Run의 전체 노드 입력·출력',
 h?.nodes?.length?'<p>Run '+escapeHtml(h.workflow_run_id)+' · 기록 '+h.nodes.length+'개</p>'+
 '<div class="stack">'+h.nodes.map(x=>'<details class="item"><summary><b>'+escapeHtml(x.node_id)+' · '+escapeHtml(x.status)+'</b></summary>'+
 '<h4>입력</h4><pre class="log">'+escapeHtml(pretty(x.input_json?.last_block||x.input_json))+'</pre>'+
 '<h4>출력</h4><pre class="log">'+escapeHtml(pretty(x.output_json?.last_block||x.output_json))+'</pre>'+
 '</details>').join('')+'</div>':
 '<div class="empty">위 실행기록의 Run 원본 확인 버튼을 선택하세요.</div>')+
 card('원본 기준 결재·증빙 상태',proposalView(r?.records?.at(-1)?.output_json));
}
async function load(){
 if(caseState.loading||caseState.catalog&&caseState.workflow)return;
 caseState.loading=true;
 try{
  const [catalog,response]=await Promise.all([
   getJSON('/public-case-feature-catalog.json'),
   getJSON(ROOT)
  ]);
  if(catalog.features?.length!==104||catalog.manifest_blocks?.length!==43||response.workflow?.nodes?.length!==43)
   throw Error("ORIGINAL_43_BLOCK_104_FEATURE_CONTRACT_INVALID");
  if(response.workflow.meta?.studioDefaultInput?.bid_no!==catalog.case.bid_no)
   throw Error("SELECTED_CASE_IDENTITY_MISMATCH");
  caseState.catalog=catalog;caseState.workflow=response.workflow;caseState.loadError=null;
  await refresh();
 }catch(e){caseState.loadError=e.message;}
 finally{caseState.loading=false;changed();}
}
async function refresh(){
 const status=await getJSON('/api/procurement/console/status');
 caseState.latestRuns=(status.recent_runs||[]).filter(x=>x.workflow===WF);
 changed();
}
async function step(){
 const r=caseState.run;
 if(!r||r.records.length>=43)return;
 if(caseState.cancel)throw Error("STOPPED_BY_USER");
 const n=r.workflow.nodes[r.records.length];
 const first=r.records.length===0;
 const body=first?
  {workflow:WF,node_id:n.id,input_json:r.workflow.meta.studioDefaultInput}:
  {workflow:WF,node_id:n.id,source_run_id:r.records.at(-1).run_id};
 const result=await getJSON(first?'/api/studio/node01/execute':'/api/studio/nodes/execute',{
  method:'POST',headers:{"Content-Type":"application/json","X-Studio-Node-Run":first?"N01":"APPROVED"},
  body:JSON.stringify(body)
 });
 if(result.status!=='SUCCESS')throw Error(result.error||'NODE_FAILED');
 if(!first&&result.workflow_run_id!==r.workflowRunId)throw Error("CROSS_CASE_RUN_ID_MISMATCH");
 if(!result.output_json||result.output_json.bid_no!=="R26BK01787028"||
    result.output_json.official_evidence_verified!==false||
    result.output_json.simulation_only!==true||
    result.output_json.bid_submitted!==false)
   throw Error("PUBLIC_CASE_OUTPUT_PROVENANCE_INVALID");
 r.workflowRunId=result.workflow_run_id;
 r.records.push({...result,node_id:n.id});
 caseState.selectedNode=n.id;
 if(r.records.length===43){
  if(Object.keys(result.output_json.feature_results||{}).length!==104 ||
     result.output_json.strategy_decision!=="HOLD_OFFICIAL_EVIDENCE")
    throw Error("PUBLIC_104_FINAL_AUDIT_INVALID");
  r.status="COMPLETE";
 }else r.status="PAUSED";
 changed();
}
async function run(which){
 if(caseState.busy)return;
 caseState.busy=true;caseState.cancel=false;
 try{
  await load();
  if(caseState.loadError)throw Error(caseState.loadError);
  if(which==='start'||!caseState.run||caseState.run.status==='COMPLETE'||caseState.run.status==='FAILED'||caseState.run.status==='STOPPED'){
   caseState.run={market:'public',workflow:caseState.workflow,records:[],workflowRunId:null,status:'RUNNING'};
  }
  let r=caseState.run;r.status='RUNNING';changed();
  if(which==='all'){
   while(r.records.length<43&&!caseState.cancel){await step();r=caseState.run;}
  }else if(!caseState.cancel)await step();
  r.status=caseState.cancel?'STOPPED':r.records.length===43?'COMPLETE':'PAUSED';
  await refresh();
 }catch(e){
  if(caseState.run)caseState.run.status=caseState.cancel?'STOPPED':'FAILED';
  caseState.loadError=e.message;
 }finally{caseState.busy=false;changed();}
}
async function openHistory(id){
 try{
  let out=await getJSON('/api/procurement/console/run?workflow_run_id='+encodeURIComponent(id));
  if(out.workflow!==WF||out.simulation_only!==true)throw Error("CASE_RUN_MISMATCH");
  caseState.history=out;changed();
 }catch(e){caseState.loadError=e.message;changed();}
}
document.addEventListener('click',e=>{
 const b=e.target.closest('[data-public-action]');if(!b)return;
 e.preventDefault();const key=b.dataset.publicAction;
 if(key==='start')return run('start');
 if(key==='next')return run('next');
 if(key==='all')return run('all');
 if(key==='stop'){caseState.cancel=true;changed();return;}
 if(key==='reset'){if(!caseState.busy){caseState.run=null;caseState.selectedNode=null;caseState.loadError=null;changed();}return;}
 if(key==='select'){if(!caseState.busy){caseState.run=null;caseState.selectedNode=null;changed();}return;}
 if(key==='inspect'){caseState.selectedNode=b.dataset.node;changed();return;}
 if(key==='history')return openHistory(b.dataset.run);
});
function renderWithError(html){
 return caseState.loadError?info('확인 또는 실행 오류: '+escapeHtml(caseState.loadError),true)+html:html;
}
window.PublicCase={
 state:caseState,
 load,refresh,renderOverview:()=>renderWithError(renderOverview()),
 renderOpportunity:()=>renderWithError(renderOverview()),
 renderPublic:()=>renderWithError(renderPublic()),
 renderTests:()=>renderWithError(renderTests()),
 renderFeatures:()=>renderWithError(renderFeatures()),
 renderStrategy:()=>renderWithError(renderStrategy()),
 renderAudit:()=>renderWithError(renderAudit())
};
load();
})();
