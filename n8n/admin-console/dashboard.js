
'use strict';
(function(){
const MARKETS={
 public:{key:'public',short:'A',title:'공공입찰 · 낙찰데이터 기반 수주전략',flow:'operations/A01-public-win-strategy.json',caseId:'DEMO_PUBLIC_001',icon:'▣',
  claim:'정확한 10자리 세부품명과 발주기관을 기준으로 과거 실제 투찰·개찰·낙찰을 연결한 뒤 경쟁과 가격, 기술제안서의 우선순위를 결정',
  agents:['RFP·평가조건 검증','정확한 10자리 세부종목','10년 개찰·낙찰 원본 대조','경쟁업체·기관 분석','가격·원가 시나리오','수주전략 결정','제안서 설계','독립 감사'],
  evidence:'현재 5개 가상 낙찰 표본만 사용. 실제 10년 원본·업체별 투찰·평가자료 검증은 미실시',
  result:'공식 증빙 부재 때문에 HOLD가 나오는 것이 정상',
  source:'나라장터 공고·첨부·개찰·낙찰·계약'},
 private_dev:{key:'private_dev',short:'B',title:'민간 프로그램 개발 외주 · 기술·견적전략',flow:'operations/B01-private-software-proposal.json',caseId:'DEMO_PRIVATE_001',icon:'⌘',
  claim:'고객이 요청한 기능을 어떻게 구현할지 검토한 뒤 개발공수·투입인력·일정·수익성을 계산해 맞춤형 영업제안서를 결정',
  agents:['고객 요구·검수조건','기술 아키텍처','기능별 WBS','개발공수·일정','개발원가·견적','수주 제안전략','계약·수익성 심사'],
  evidence:'가상의 고객 요구와 공수·일당만 사용. 실제 고객 계약, 견적 제출은 없음',
  result:'모의 수익성 계산 완료 후 고객 제안 전 사람 검토',
  source:'개발 의뢰·고객 요구·포트폴리오'},
 staffing:{key:'staffing',short:'C',title:'민간 인력·단순 용역 · 수급·운영전략',flow:'operations/C01-staffing-service-proposal.json',caseId:'DEMO_STAFFING_001',icon:'♙',
  claim:'고용24 등 구인정보와 용역 발주를 구분하고, 인력의 실제 확보 가능성·급여·관리비·법률 요건을 확인해 용역제안을 결정',
  agents:['고객 인력 수요','채용 vs 용역 구분','수급·대체인력','인건비·관리비','도급·파견 노무검토','운영계획·단가','독립 감사'],
  evidence:'가상 인력 3명과 6개월 수요를 사용. 고용24 실조회·실제 인력검증·노무 법률검토 없음',
  result:'실제 인력·법률 검토가 없으므로 HOLD가 정상',
  source:'고용24·사람인·잡코리아 수요 신호 + 별도 용역 의뢰'}
};
const M=[
 ['overview','종합 관제센터','사업기회·전략·실행·DB 총괄','◫','platform'],
 ['opportunities','사업기회·접수센터','발주·개발 의뢰·인력 수요의 구분','⌕','platform'],
 ['public','공공조달 수주전략','과거 낙찰 → 경쟁·가격 → 제안서','▣','markets'],
 ['private_dev','민간 SW 개발 외주','기술설계·공수·견적·영업제안','⌘','markets'],
 ['staffing','민간 인력·단순 용역','수급·노무·운영·단가','♙','markets'],
 ['strategy','수주전략·제안서','가격·마진·제안서·판단 근거','◈','operations'],
 ['workflows','워크플로·노드 관제','공용 Studio · PF00~PF15 · A/B/C','⤴','operations'],
 ['tests','통합 실행 테스트센터','노드별 실제 Python 모의 처리·입출력','▶','operations'],
 ['features','104기능·43블록 현황','7개 업무분야 계약·커버리지 점검','▦','verification'],
 ['audit','실행 이력·독립 감사','SQLite 실행 ID · 원본 · 오류 · HOLD','≋','verification'],
 ['infra','시스템·DB 상태','건수·연동·데이터 출처·안전제약','⚙','verification']
];
const FGROUPS=[
 {from:1,to:16,label:'공고 수집·정정·취소·중복'},
 {from:17,to:32,label:'상세 공고·첨부·원본 증빙'},
 {from:33,to:48,label:'과거 10년 실제 개찰·낙찰'},
 {from:49,to:60,label:'세부종목·기관·경쟁 분석'},
 {from:61,to:76,label:'자격·공급업체·인력'},
 {from:77,to:94,label:'원가·투찰전략·서류'},
 {from:95,to:104,label:'운영·검증·감사'}
];
const SCENARIOS=[
 ['S01','정상 발주'],['S02','대상 외 공고'],['S03','세부종목 미확인'],['S04','정정공고 버전'],
 ['S05','API 429·503 장애'],['S06','필수 자격 미충족'],['S07','견적 정족수 미달'],
 ['S08','Worker 장애 복구'],['S09','독립 감사 오류'],['S10','동시 발주 경합']
];
const state={
 page:M.some(x=>x[0]===new URLSearchParams(location.search).get('section'))
  ?new URLSearchParams(location.search).get('section'):'overview',
 market:'public',preference:'balanced',
 health:null,server:null,manifest:null,
 workflows:{},run:null,selectedNode:null,historyRun:null,
 busy:false,stopRequested:false,featureFilter:'',flowSearch:'',error:'',lastRefresh:null
};
const el=id=>document.getElementById(id);
const esc=v=>String(v===null||v===undefined?'':v).replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const safeJson=v=>JSON.stringify(v===undefined?null:v,null,2);
const market=k=>MARKETS[k]||MARKETS.public;
const flowUrl=p=>'/?workflow='+encodeURIComponent(p);
const nodesOf=r=>r?.workflow?.nodes||[];
const namesOf=w=>new Set((w||[]).map(x=>x.name));
const metric=(label,value,hint)=>'<div class="metric"><div class="legend">'+esc(label)+'</div><div class="num">'+esc(value)+'</div><small>'+esc(hint)+'</small></div>';
const badge=(value,style)=>'<span class="badge '+(style||'')+'">'+esc(value)+'</span>';
const linkFlow=(f,label)=>'<a class="btn small" href="'+esc(flowUrl(f))+'" target="_blank" rel="noopener">'+esc(label||'↗ 기존 노드 캔버스 열기')+'</a>';
const htmlCard=(title,body)=>'<section class="panel"><h3>'+esc(title)+'</h3>'+body+'</section>';
const notice=(t,warning=false)=>'<div class="notice '+(warning?'warn':'')+'">'+t+'</div>';
const click=(name,text,cls='',extra='')=>'<button type="button" class="btn '+cls+'" data-action="'+esc(name)+'" '+extra+'>'+esc(text)+'</button>';
function typeGroup(page){return M.find(x=>x[0]===page)||M[0];}
function fmtDate(s){if(!s)return '기록 없음';const d=new Date(s);return Number.isNaN(d.valueOf())?esc(s):d.toLocaleString('ko-KR',{timeZone:'Asia/Seoul'});}
async function api(uri,options={}){
 const r=await fetch(uri,{credentials:'same-origin',cache:'no-store',...options});
 let j;try{j=await r.json()}catch{throw Error('JSON 응답이 아닙니다 · HTTP '+r.status);}
 if(!r.ok)throw Error(j.error||j.detail||('HTTP '+r.status));
 return j;
}
function popup(s,failed=false){
 const t=el('toast');if(!t)return;
 t.textContent=s;t.style.borderColor=failed?'#aa5c5c':'#5a90c2';
 t.classList.add('show');clearTimeout(popup.timer);popup.timer=setTimeout(()=>t.classList.remove('show'),4000);
}
function header(){
 const a=typeGroup(state.page),hh=el('server-health');
 el('page-title').textContent=a[1];el('page-subtitle').textContent=a[2];
 el('breadcrumb').textContent='PROCUREFLOW / '+a[0].toUpperCase();
 hh.textContent=state.health?.status==='ok'
  ?(state.health.projectAdapterConnected?'SQLite · 모의 노드 연결':'SQLite · 모의 노드 미연결')
  :'연결 확인 필요';
 hh.className='health '+(state.health?.status==='ok'&&state.health.projectAdapterConnected?'good':'bad');
}
function menu(){
 let last='',out='';
 for(const [id,label,subtitle,ico,group] of M){
  if(group!==last){out+='<div class="nav-group">'+esc({platform:'플랫폼 운영',markets:'사업별 전문 에이전트',operations:'실행·의사결정',verification:'검증·시스템'}[group])+'</div>';last=group;}
  out+='<button class="nav '+(state.page===id?'active':'')+'" data-page="'+esc(id)+'" title="'+esc(subtitle)+'"><span class="ico">'+esc(ico)+'</span><span>'+esc(label)+'</span></button>';
 }
 el('side-menu').innerHTML=out;
}
const recent=()=>state.server?.recent_runs||[];
const counts=()=>state.server?.metrics||{};
const totals=()=>({flows:29,operations:16,scenarios:10,marketAgents:3,blocks:state.manifest?.blocks?.length??43,features:104});
function sectionHero(kicker,title,desc,extra=''){
 return '<section class="hero"><div class="kicker">'+esc(kicker)+'</div><h2>'+esc(title)+'</h2><p>'+esc(desc)+'</p>'+extra+'</section>';
}
function renderOverview(){
 const c=counts(),r=recent();let g=totals();
 return sectionHero('BUSINESS DEVELOPMENT COMMAND','발주 한 건에서 수주전략·제안서까지',
  '공공조달은 과거 개찰·낙찰 데이터와 RFP를 결합하고, 민간 개발은 기술공수·원가, 인력용역은 수급·노무를 중심으로 별도 전문 에이전트가 판단합니다. 실행되는 항목은 가상 Python 테스트만 포함됩니다.',
  '<div class="actions">'+click('goto-tests','▶ 통합 모의 실행','primary')+click('goto-opportunities','사업기회 선택')+click('goto-audit','실행 이력 확인')+'</div>')+
 '<div class="metric-grid">'+metric('전문 사업영역','3개','공공 / SW 개발 / 인력 용역')+
 metric('관리 워크플로',g.flows+'개','기존 26 + 신규 전략 3')+
 metric('기존 업무 계약',g.features+'개','43개 블록 · 실제 실행 완료 아님')+
 metric('브라우저 세션 실행',c.workflow_runs??'—','SQLite에 저장된 모의 Run')+'</div>'+
 '<div class="panels"><section class="panel"><h3>시장별 에이전트 지휘실</h3><div class="stack">'+
 Object.values(MARKETS).map(m=>'<div class="item"><div class="flow-row"><div class="meta"><b>'+esc(m.short+' · '+m.title)+'</b><p>'+esc(m.claim)+'</p></div>'+badge(m.agents.length+' 노드','')+'</div><div class="actions"><button class="btn primary small" data-page="'+m.key+'">업무센터 열기</button><button class="btn small" data-action="choose-market" data-market="'+m.key+'">모의 실행 선택</button>'+linkFlow(m.flow,'↗ 노드 캔버스')+'</div></div>').join('')+
 '</div></section><section class="panel"><h3>실제 실행·데이터 분리 현황</h3><table><tbody>'+
 '<tr><th>같은 공용 노드 편집기</th><td>'+badge('배포·검증됨','ok')+'</td></tr>'+
 '<tr><th>가상 Python 업무 노드</th><td>'+badge('22개 승인 함수','ok')+'</td></tr>'+
 '<tr><th>노드 실행·전달 기록</th><td>'+badge((c.node_runs??'—')+'건 · SQLite','')+'</td></tr>'+
 '<tr><th>공식 G2B 10년 낙찰 전수</th><td>'+badge('미실행','warn')+'</td></tr>'+
 '<tr><th>실제 n8n 전체 흐름 실행</th><td>'+badge('미연결','warn')+'</td></tr>'+
 '<tr><th>입찰참가·투찰·고객 연락</th><td>'+badge('차단','ok')+'</td></tr>'+
 '</tbody></table>'+notice('주식자동화처럼 실제 노드마다 입력·출력·실행 ID를 확인합니다. 단, 현재 데이터는 모의 원본이며 실제 낙찰 가능성이나 운영 n8n 성공으로 간주하지 않습니다.',true)+'</section></div>'+
 '<section class="panel"><h3>이 브라우저에서 최근 테스트한 실행</h3>'+recentTable(r.slice(0,6))+'</section>';
}
function opportunities(){
 return sectionHero('OPPORTUNITY INTAKE','접수 한 건 → 유형 분류 → 전문 에이전트 배정',
 '각 시장에 맞는 수주 전략을 정하기 전에 사업기회의 출처·요구조건·경쟁방식이 구분되어야 합니다. 현재 선택 가능한 입력은 허구의 3개 시험사례입니다.')+
 '<div class="matrix">'+Object.values(MARKETS).map(m=>'<article class="panel"><div class="kicker">'+esc(m.short+' / FIXTURE INTAKE')+'</div><h3>'+esc(m.title)+'</h3><p>'+esc(m.claim)+'</p><table><tbody>'+
 '<tr><th>가상 사건 ID</th><td>'+esc(m.caseId)+'</td></tr><tr><th>운영 원본</th><td>미연결</td></tr><tr><th>주요 정보원</th><td>'+esc(m.source)+'</td></tr><tr><th>수주 판단</th><td>'+esc(m.result)+'</td></tr></tbody></table>'+
 '<div class="actions"><button class="btn primary small" data-action="choose-market" data-market="'+m.key+'">이 사례 선택 후 테스트</button><button class="btn small" data-page="'+m.key+'">분석 과정</button></div></article>').join('')+'</div>'+
 notice('<strong>발주 한 건을 선택하는 것은 운영 데이터 조회와 다릅니다.</strong> 실제 발주번호·10자리 세부품명·기관·첨부 문서는 향후 검증된 데이터 어댑터에 연결해야 합니다.',true);
}
function marketPage(key){
 const m=market(key),r=recent().find(x=>x.workflow===m.flow),matches=state.run?.market===key?state.run:null;
 const decision=matches?.records?.at(-1)?.output_json?.decision||r?.decision;
 return sectionHero('SPECIALIST AGENT / '+m.short,m.title,m.claim,
 '<div class="actions">'+click('choose-market','▶ 이 시장으로 모의 테스트','primary','data-market="'+m.key+'"')+
 linkFlow(m.flow,'↗ 동일한 노드 캔버스')+'<span class="badge">'+esc(m.caseId)+'</span></div>')+
 '<div class="metric-grid">'+metric('전문 노드',m.agents.length,'시장 전용 Python 함수')+
 metric('업무 원본','가상','실제 수집 금지 유지')+
 metric('최근 결과',decision||'기록 없음','실제 평가·낙찰 판단 아님')+
 metric('영업·입찰 제출','차단','사람 승인 전 단계')+'</div>'+
 '<div class="panels"><section class="panel"><h3>판단 순서 · 전문 에이전트별 책임</h3>'+
 '<ol class="tree">'+m.agents.map((x,i)=>'<li><strong>'+(i+1)+'. '+esc(x)+'</strong> <span class="muted">— 독립 입력·출력·검증 단계</span></li>').join('')+'</ol>'+
 '</section><section class="panel"><h3>이 사업의 데이터 전략과 종료 기준</h3>'+
 '<div class="item"><b>핵심 데이터</b><p>'+esc(m.source)+'</p></div><div class="item" style="margin-top:10px"><b>실행 근거 상태</b><p>'+esc(m.evidence)+'</p></div>'+
 '<div class="item" style="margin-top:10px"><b>정상적인 테스트 판정</b><p>'+esc(m.result)+'</p></div>'+
 notice('과거 낙찰 이력만으로 낙찰업체가 제출한 기술제안서 내용이나 평가 이유를 알 수 없습니다. 근거 없는 확정을 하지 않습니다.',true)+'</section></div>'+
 '<section class="panel"><h3>테스트한 수주전략의 산출물</h3>'+ (matches?.records?.length
 ?strategySummary(matches.records.at(-1).output_json,key)
 :'<div class="empty">이 시장의 모의 노드를 실행하면 선택한 전략·가격·제안서·감사 근거가 여기에 표시됩니다.<div class="actions">'+click('choose-market','테스트센터로 이동','primary','data-market="'+m.key+'"')+'</div></div>')+'</section>';
}
function strategySummary(out,key){
 if(!out)return '<div class="empty">수주전략 생성 기록 없음</div>';
 let rows=[],proposal=out.proposal||{};
 if(key==='public'){
  rows=[['10자리 세부품명',out.rfp?.detail10||'미확인'],['과거 표본 출처',out.award_history?.source||'기록 없음'],
   ['과거 10년 전수 검증',out.award_history?.ten_year_coverage_verified?'완료':'미실행 · 전수 증빙 없음'],
   ['가상 표본 평균 낙찰률',out.award_history?.mean_ratio!==undefined?(100*out.award_history.mean_ratio).toFixed(2)+'%':'미산출'],
   ['선택 가격전략',out.win_strategy?.selected?.name||'미선택'],['가상 제안서 강조',proposal.emphasis||'미작성'],
   ['독립 감사',out.decision||'미결정']];
 }else if(key==='private_dev'){
  rows=[['가상 개발공수',out.effort?.total_person_days!==undefined?out.effort.total_person_days+'인일':'미산출'],
   ['가상 일정',out.effort?.schedule_weeks!==undefined?out.effort.schedule_weeks+'주':'미산출'],
   ['선택 견적안',proposal.strategy||'미선택'],
   ['가상 마진',proposal.quote?.margin_pct!==undefined?proposal.quote.margin_pct+'%':'미산출'],
   ['고객 제안',out.decision||'미결정']];
 }else{
  rows=[['수요 분류',out.demand?.source_type||'미확인'],['가상 인원',out.demand?.headcount||'미확인'],
   ['총 용역 단가(가상)',out.staffing_cost?.quote_krw?.toLocaleString('ko-KR')||'미산출'],
   ['노무 검토 완료',out.compliance?.legal_review_completed?'확인':'미확인'],
   ['최종 검토',out.decision||'미결정']];
 }
 return '<table><tbody>'+rows.map(([k,v])=>'<tr><th>'+esc(k)+'</th><td>'+esc(v)+'</td></tr>').join('')+'</tbody></table>'+
 (proposal.sections?'<h4>제안서 구성 방향</h4><div class="stack">'+proposal.sections.map(x=>'<div class="item"><b>'+esc(x)+'</b></div>').join('')+'</div>':'')+
 '<details style="margin-top:12px"><summary>전체 JSON 근거 보기</summary><pre class="log">'+esc(safeJson(out))+'</pre></details>';
}
function strategyPage(){
 const r=state.run,other=recent().slice(0,5);
 return sectionHero('STRATEGY BEFORE PROPOSAL','제안서를 작성하기 전에 무엇으로 이길지 결정',
  '공공은 낙찰·평가 데이터의 증거 수준, 개발 외주는 기술공수·견적·마진, 인력용역은 수급·노무 위험을 먼저 검증합니다. 전략 결정서를 만들고 나서만 제안서 초안을 진행합니다.')+
 '<div class="panels"><section class="panel"><h3>시장별 전략 결정 변수</h3><table><thead><tr><th>유형</th><th>승리 조건</th><th>제안서 차별화</th></tr></thead><tbody>'+
 '<tr><td>공공조달</td><td>낙찰/평가방식·경쟁·원가</td><td>RFP 평가항목별 기술·실적·인력</td></tr>'+
 '<tr><td>민간 SW</td><td>요구 충족·납기·마진</td><td>아키텍처·범위·WBS·견적</td></tr>'+
 '<tr><td>민간 인력용역</td><td>인력확보·노무 준수·단가</td><td>인력배치·교대·대체·운영계획</td></tr>'+
 '</tbody></table></section><section class="panel"><h3>전략 검증의 완료 기준</h3><div class="stack">'+
 ['분류·원본 버전 및 출처','전략 대안 2~3개 비교','원가·마진·평가 조건 검토','제안서 강조항목과 전략 연결','증빙 누락·HOLD 기록','사람의 최종 승인'].map(x=>'<div class="item"><b>'+esc(x)+'</b></div>').join('')+
 '</div></section></div><section class="panel"><h3>현재 선택된 시험 결과</h3>'+
 (r?.records?.length?strategySummary(r.records.at(-1).output_json,r.market):'<div class="empty">아직 선택된 시험 결과가 없습니다.</div>')+
 '<h4>최근 전략 시험</h4>'+recentTable(other)+'</section>';
}
function flowCatalog(){
 const flows=[];
 Object.values(MARKETS).forEach(m=>flows.push({path:m.flow,title:m.title,group:'전략 A/B/C'}));
 for(let i=0;i<16;i++)flows.push({path:'operations/PF'+String(i).padStart(2,'0')+'.json',
 title:'PF'+String(i).padStart(2,'0')+' · '+['통합 조정','공고 수집','등록·1차 심사','작업 배정','첨부 처리','10년 입찰·낙찰','경쟁업체','자격','공급·인력','가격전략','제안서','독립 감사','참가 결정','정정·버전','자원 통제','복구'][i],group:'기존 운영'});
 for(const [id,label] of SCENARIOS)flows.push({path:'scenarios/'+id+'.json',title:id+' · '+label,group:'기존 합성 시나리오'});
 return flows;
}
function workflowsPage(){
 const flows=flowCatalog().filter(f=>(f.title+' '+f.path).toLowerCase().includes(state.flowSearch.toLowerCase()));
 return sectionHero('OPERATIONS / 29 WORKFLOWS','실제 운영 설계와 시험 실행을 구분하는 워크플로 관제',
  '공용 Studio와 완전히 동일한 노드 카드에서 설정·이력·실행을 조작합니다. PF00~PF15 및 S01~S10은 보존되며, A/B/C 3개 노드 플로우는 Python 모의 실행이 연결돼 있습니다.')+
 '<div class="metric-grid">'+metric('전략 전문 워크플로','3','A 8 / B 7 / C 7 노드')+metric('기존 운영 워크플로','16','PF00~PF15')+
 metric('기존 합성 시나리오','10','S01~S10')+metric('등록된 전체','29','복원 가능한 JSON')+'</div>'+
 '<section class="panel"><div class="flow-row"><h3>워크플로 목록</h3><input id="flow-search" class="input" style="max-width:280px" placeholder="워크플로 검색" value="'+esc(state.flowSearch)+'" aria-label="워크플로 검색"></div>'+
 '<div class="table-wrap"><table><thead><tr><th>구분</th><th>워크플로</th><th>실행 상태</th><th>조작</th></tr></thead><tbody>'+
 flows.map(f=>'<tr><td>'+esc(f.group)+'</td><td><b>'+esc(f.title)+'</b><div class="muted smalltxt">'+esc(f.path)+'</div></td>'+
 '<td>'+badge(f.group==='전략 A/B/C'?'Python 모의 실행 가능':f.group==='기존 합성 시나리오'?'모의 화면':'업무 엔진 미검증',f.group==='전략 A/B/C'?'ok':'warn')+'</td>'+
 '<td>'+linkFlow(f.path,'↗ 노드 캔버스')+(f.group==='전략 A/B/C'?'<button class="btn small primary" data-action="choose-market" data-market="'+Object.values(MARKETS).find(m=>m.flow===f.path).key+'">▶ 모의 실행</button>':'')+'</td></tr>').join('')+'</tbody></table></div></section>';
}
function progressBlock(r){
 if(!r)return '<div class="empty">아직 선택된 시험 실행이 없습니다. 시작을 누르면 실제 Python 모의 노드 함수가 호출됩니다.</div>';
 const pct=r.workflow?.nodes?.length?Math.round(r.records.length/r.workflow.nodes.length*100):0;
 return '<div class="runline">'+badge(r.status,r.status==='FAILED'?'error':r.status==='COMPLETED'?'ok':'warn')+
 '<span class="muted smalltxt">Run '+esc(r.workflowRunId||'실행 전')+'</span><span class="muted smalltxt">'+r.records.length+'/'+r.workflow.nodes.length+' 노드</span></div>'+
 '<div class="progress" style="margin:12px 0"><div class="bar" style="width:'+pct+'%"></div></div>';
}
function testControls(){
 const m=market(state.market),busy=state.busy,r=state.run;
 const hasRun=r?.market===state.market,remaining=hasRun&&r.records.length<r.workflow.nodes.length;
 return '<div class="two-cols"><label class="label">시장별 전문 에이전트<select class="select" id="market-select">'+
 Object.values(MARKETS).map(x=>'<option value="'+x.key+'" '+(x.key===state.market?'selected':'')+'>'+esc(x.short+' · '+x.title)+'</option>').join('')+'</select></label>'+
 '<label class="label">전략 선호도 (가상 가격/견적 비교)<select class="select" id="preference-select">'+
 [['balanced','균형형'],['quality','기술·품질 우위'],['cost','비용 효율형']].map(([v,n])=>'<option value="'+v+'" '+(state.preference===v?'selected':'')+'>'+esc(n)+'</option>').join('')+'</select></label></div>'+
 '<p class="muted smalltxt">사례: <b>'+esc(m.caseId)+'</b> · 원본: 가상 입력 · 공개 데이터·고용24·입찰 버튼 호출 없음</p>'+
 '<div class="actions">'+
 click('start-root','① N01 모의 실행 시작','primary',busy?'disabled':'')+
 click('next-step','② 다음 노드', '',(!hasRun||!remaining||busy)?'disabled':'')+
 click('run-all','▶ 전체 노드 모의 실행','green',busy?'disabled':'')+
 click('stop-run','■ 실행 중지','stop',!busy?'disabled':'')+
 click('reset-run','초기화','outline',busy?'disabled':'')+
 linkFlow(m.flow,'↗ 실제 노드 편집 화면')+'</div>'+
 notice('노드를 실제 호출하더라도 결과는 테스트용 Python 코드가 산출한 모의 데이터입니다. 본 화면의 Run ID는 Studio SQLite 테스트 기록이며, 운영 n8n 엔진 Execution ID가 아닙니다.',true);
}
function inspectPanel(){
 const r=state.run;
 if(!r)return '<div class="empty">노드별 입력·출력 조회를 위해 실행을 시작하세요.</div>';
 const hit=r.records.find(x=>x.node_id===state.selectedNode)||r.records.at(-1);
 if(!hit)return '<div class="empty">N01부터 실행할 수 있습니다.</div>';
 const node=r.workflow.nodes.find(n=>n.id===hit.node_id);
 return '<h4>'+esc(node?.name||hit.node_id)+'</h4><p class="muted smalltxt">run_id: '+esc(hit.run_id)+' · status: '+esc(hit.status)+
 ' · '+esc(hit.duration_ms??'—')+'ms · '+esc(hit.code_version||hit.code_ref||'검증된 Python 모듈')+'</p>'+
 '<h4>노드 INPUT · 앞 단계 실제 전달 JSON</h4><pre class="log">'+esc(safeJson(hit.input_json))+'</pre>'+
 '<h4>노드 OUTPUT · 테스트 함수가 계산한 결과</h4><pre class="log">'+esc(safeJson(hit.output_json))+'</pre>'+
 '<h4>오류·차단 원인</h4><pre class="log">'+esc(hit.error||'기록 없음')+'</pre>';
}
function testsPage(){
 const r=state.run,m=market(state.market);
 const n=r?.workflow?.nodes||[],records=r?.records||[];
 return sectionHero('NODE EXECUTION TEST LAB','투자 WF01처럼 한곳에서 선택·실행·입출력·이력 확인',
  '기존 공용 Studio의 승인된 Python 노드 엔드포인트를 순서대로 호출하고, 실제 응답과 SQLite 기록 ID를 이 화면에 표시합니다. S01~S10은 원본 시나리오 화면에서 별도로 실행합니다.')+
 '<section class="panel"><h3>실행 대상·전략 선택</h3>'+testControls()+progressBlock(r)+'</section>'+
 '<div class="panels"><section class="panel"><h3>노드별 실행 과정</h3>'+
 (r?'<div class="timeline">'+n.map((node,i)=>{let result=records.find(x=>x.node_id===node.id);
 return '<button type="button" class="step '+(result?(result.status==='SUCCESS'?'done':'failed'):'')+
 (state.selectedNode===node.id?' selected':'')+'" data-action="inspect-node" data-node="'+esc(node.id)+'">'+
 '<strong>'+esc(node.name)+'</strong><small>'+esc(node.id)+' · '+esc(result?(result.status+' · '+(result.duration_ms??0)+' ms'):'미실행')+'</small></button>';
 }).join('')+'</div>':'<div class="empty">선택한 시장의 N01을 실행하면 노드별 진척이 표시됩니다.</div>')+
 '</section><section class="panel"><h3>선택 노드의 실제 모의 실행 I/O</h3>'+inspectPanel()+'</section></div>'+
 '<div class="panels"><section class="panel"><h3>현재 단계 최종 전략·검증</h3>'+
 (records.length?strategySummary(records.at(-1).output_json,m.key):'<div class="empty">실행 결과가 없습니다.</div>')+
 '</section><section class="panel"><h3>이 브라우저의 이전 실행 기록</h3>'+recentTable(recent().slice(0,8))+'</section></div>'+
 '<section class="panel"><h3>S01~S10 오류·장애 합성 시나리오</h3><div class="matrix">'+SCENARIOS.map(([id,label])=>'<div class="item"><b>'+esc(id+' · '+label)+'</b><p>기존 n8n 모의 시나리오 JSON</p><div class="actions">'+linkFlow('scenarios/'+id+'.json','↗ 시나리오 테스트')+'</div></div>').join('')+'</div></section>';
}
function featuresPage(){
 const manifest=state.manifest,g=totals(),blocks=manifest?.blocks||[];
 let featureMap=new Map();
 for(const b of blocks)for(const n of b.features||[])featureMap.set(n,[...(featureMap.get(n)||[]),b]);
 const q=state.featureFilter.trim().toLowerCase();
 const rows=Array.from({length:104},(_,i)=>i+1).map(n=>{
 const b=featureMap.get(n)||[],group=FGROUPS.find(x=>x.from<=n&&n<=x.to);
 return {n,b,group};
 }).filter(x=>(String(x.n)+' '+x.group?.label+' '+x.b.map(b=>b.label).join(' ')).toLowerCase().includes(q));
 return sectionHero('CONTRACT COVERAGE AND QA','104개 기능·43개 업무 블록별 개발 현황',
  '2026-10-28 최종 기획의 104개 기능과 43개 블록을 보존합니다. 여기 표시된 매핑 검증은 실제 공식 API 구현이나 과거 10년 데이터 수집 완료가 아닙니다.')+
 '<div class="metric-grid">'+metric('기능 계약',g.features,'7개 분야')+metric('업무 블록',blocks.length||'—','고유 블록')+
 metric('연결된 기능번호',featureMap.size,'manifest 기준')+metric('운영 기능 실데이터 검증','0','이 센터에서는 수행하지 않음')+'</div>'+
 '<section class="panel"><h3>7개 전문 기능 영역</h3><div class="matrix">'+FGROUPS.map(x=>{
 const n=Array.from({length:x.to-x.from+1},(_,i)=>i+x.from).filter(i=>featureMap.has(i)).length;
 return '<div class="item"><b>'+esc(x.label)+'</b><p>기능번호 '+x.from+'–'+x.to+' / '+n+'개 매핑</p>'+badge('실운영 검증 별도','warn')+'</div>';
 }).join('')+'</div></section>'+
 '<section class="panel"><div class="flow-row"><h3>개별 기능·블록 검색</h3><input class="input" id="feature-filter" style="max-width:260px" value="'+esc(state.featureFilter)+'" placeholder="예: 33, 낙찰, 자격" aria-label="기능 검색"></div>'+
 '<div class="table-wrap"><table><thead><tr><th>번호</th><th>분야</th><th>담당 업무 블록</th><th>판정</th></tr></thead><tbody>'+
 rows.map(({n,b,group})=>'<tr><td><b>F'+String(n).padStart(3,'0')+'</b></td><td>'+esc(group?.label||'분류 미상')+'</td>'+
 '<td>'+esc(b.map(x=>x.id+' · '+x.label).join(', ')||'매핑 없음')+'</td><td>'+
 badge(b.length?'계약 매핑':'계약 누락',b.length?'':'error')+'</td></tr>').join('')+'</tbody></table></div></section>';
}
function recentTable(runs){
 if(!runs?.length)return '<div class="empty">현재 브라우저 세션에 저장된 모의 실행 기록이 없습니다.</div>';
 return '<div class="table-wrap"><table><thead><tr><th>시각</th><th>대상</th><th>노드</th><th>최종 판단</th><th>상세</th></tr></thead><tbody>'+
 runs.map(r=>{
 const m=Object.values(MARKETS).find(x=>x.flow===r.workflow);
 return '<tr><td>'+esc(fmtDate(r.last_at))+'</td><td>'+esc(m?.short+' · '+m?.title||r.workflow)+'</td><td>'+esc(r.completed_nodes)+'개</td>'+
 '<td>'+badge(r.decision||r.last_status,r.decision?.includes('HOLD')?'warn':'')+'</td>'+
 '<td><button type="button" class="btn small" data-action="load-run" data-run="'+esc(r.workflow_run_id)+'">실행 증빙 보기</button></td></tr>';
 }).join('')+'</tbody></table></div>';
}
function auditPage(){
 const old=state.historyRun,all=recent();
 return sectionHero('IMMUTABLE TRACE / QA','실행 이력·노드 증빙·독립 감사',
  'Run ID는 서버 SQLite에 저장된 실제 모의 Python 실행 기록을 가리킵니다. 발주번호·원본 URL·공식 10년 낙찰 근거와 연결되기 전까지는 실증 분석으로 인정하지 않습니다.')+
 '<div class="metric-grid">'+metric('실행 Run',counts().workflow_runs??'—','현재 브라우저 세션')+
 metric('노드 실행 기록',counts().node_runs??'—','SQLite node_runs')+
 metric('전달선 기록',counts().edge_transfers??'—','SQLite edge_transfers')+
 metric('실제 낙찰증빙','미연결','가상 입력만')+'</div>'+
 '<section class="panel"><h3>최근 실행 기록</h3>'+recentTable(all)+'</section>'+
 '<section class="panel"><h3>선택한 실행의 노드별 저장 기록</h3>'+(
 old?.nodes?.length?'<p class="smalltxt muted">Run '+esc(old.workflow_run_id)+' · '+esc(old.workflow)+' · '+old.nodes.length+'단계</p>'+
 '<div class="stack">'+old.nodes.map(n=>'<details class="item"><summary><b>'+esc(n.node_id+' · '+n.status)+'</b><span class="muted smalltxt">'+esc(n.duration_ms??0)+'ms · '+esc(n.run_id)+'</span></summary>'+
 '<h4>INPUT</h4><pre class="log">'+esc(safeJson(n.input_json))+'</pre><h4>OUTPUT</h4><pre class="log">'+esc(safeJson(n.output_json))+'</pre>'+
 '<h4>오류</h4><pre class="log">'+esc(n.error||'없음')+'</pre></details>').join('')+'</div>':
 '<div class="empty">실행 목록의 “실행 증빙 보기”를 누르면 해당 브라우저 세션에 저장된 실제 테스트 기록이 나타납니다.</div>')+'</section>';
}
function infraPage(){
 const c=counts(),h=state.health||{};
 return sectionHero('INFRASTRUCTURE / DATA GATES','시스템·DB 연결과 안전제약',
  '이 페이지는 실제 연결된 서비스만 연결됨으로 표시합니다. 운영 n8n 엔진, 공식 G2B 데이터, 실제 고객 시스템이 연결돼 있다고 추정하지 않습니다.')+
 '<div class="metric-grid">'+metric('Studio /health',h.status||'확인 중','공용 Studio 서버')+
 metric('프로젝트 Python 어댑터',h.projectAdapterConnected?'연결':'미연결','허가된 가상 노드만')+
 metric('SQLite node_runs',c.node_runs??'—','브라우저 세션 단위')+metric('현재 세션 초안',c.drafts??'—','SQLite snapshots')+'</div>'+
 '<div class="panels"><section class="panel"><h3>데이터·실행 연결 상태</h3><table><tbody>'+
 [['공용 Vue Flow 편집기','연결','ok'],['서버 SQLite 초안·노드 실행','연결','ok'],
 ['공공 10년 입찰·낙찰 실제 자료','미수집','warn'],['기존 공식 n8n 운영 엔진','본 콘솔과 미연결','warn'],
 ['운영 PostgreSQL 실제 분석이력','미확인','warn'],['공공/민간 외부 수집','비활성','ok'],
 ['관리자 계정 생성','수행 안 함','ok'],['입찰 투찰·고객 연락','수행 안 함','ok']].map(([k,v,s])=>'<tr><th>'+esc(k)+'</th><td>'+badge(v,s)+'</td></tr>').join('')+
 '</tbody></table></section><section class="panel"><h3>세션별 SQLite 기록</h3><table><tbody>'+
 Object.entries(c).map(([k,v])=>'<tr><th>'+esc(k)+'</th><td>'+esc(v===null?'미확인':v)+'</td></tr>').join('')+
 '</tbody></table><h4>운영 경계</h4>'+notice('현재 테스트 로그의 n8n Execution ID는 없습니다. 전체 공식 n8n 실행, G2B 실조회, 입찰제출은 시험 범위 밖입니다.',true)+'</section></div>'+
 '<section class="panel"><h3>개발 및 유지보수 링크</h3><div class="actions">'+
 '<a class="btn small" target="_blank" rel="noopener" href="https://github.com/lyonbegin/procureflow/pull/25">조달청 3개 시장 개발 PR ↗</a>'+
 '<a class="btn small" target="_blank" rel="noopener" href="https://github.com/lyonbegin/shared-n8n-studio">공용 Studio 소스 ↗</a>'+
 '<a class="btn small" target="_blank" rel="noopener" href="https://github.com/lyonbegin/procureflow/actions">GitHub 테스트 CI ↗</a>'+
 '</div></section>';
}
function render(){
 menu();header();
 const content={
 overview:renderOverview,opportunities:opportunities,public:()=>marketPage('public'),
 private_dev:()=>marketPage('private_dev'),staffing:()=>marketPage('staffing'),
 strategy:strategyPage,workflows:workflowsPage,tests:testsPage,features:featuresPage,
 audit:auditPage,infra:infraPage
 };
 el('content').innerHTML=(content[state.page]||renderOverview)();
}
async function loadHealth(){
 try{state.health=await api('/api/studio/health');}
 catch(e){state.health={status:'error',error:e.message};}
}
async function loadStatus(){
 try{state.server=await api('/api/procurement/console/status');}
 catch(e){state.server={metrics:{},recent_runs:[],status:'error'};state.error=e.message;}
}
async function loadManifest(){
 try{state.manifest=await api('/procure-manifest.json');}
 catch(e){state.error=e.message;}
}
async function loadWorkflow(k){
 const m=market(k);
 if(state.workflows[k])return state.workflows[k];
 const result=await api('/api/studio/workflows/'+m.flow);
 if(!result.workflow||!Array.isArray(result.workflow.nodes))throw Error('원본 워크플로 조회 실패');
 if(result.workflow.meta?.simulation_only!==true)throw Error('가상 테스트 워크플로만 허용');
 if(result.workflow.meta.studioDefaultInput?.fixture_kind!==k)throw Error('시장별 가상 원본 계약 불일치');
 state.workflows[k]=result.workflow;
 return result.workflow;
}
async function executeOne(r){
 if(state.stopRequested)throw Error('사용자가 중지했습니다');
 let obj,node,index=r.records.length;
 if(index>=r.workflow.nodes.length)return;
 node=r.workflow.nodes[index];
 if(index===0){
  obj=await api('/api/studio/node01/execute',{method:'POST',
    headers:{'Content-Type':'application/json','X-Studio-Node-Run':'N01'},
    body:JSON.stringify({workflow:r.path,node_id:node.id,input_json:{
      ...r.workflow.meta.studioDefaultInput,strategy_preference:state.preference}})});
  r.workflowRunId=obj.workflow_run_id||obj.run_id;
 }else{
  obj=await api('/api/studio/nodes/execute',{method:'POST',
    headers:{'Content-Type':'application/json','X-Studio-Node-Run':'APPROVED'},
    body:JSON.stringify({workflow:r.path,node_id:node.id,source_run_id:r.records[index-1].run_id})});
  if(obj.workflow_run_id!==r.workflowRunId)throw Error('이전 실행과 workflow_run_id가 다릅니다');
 }
 if(obj.status!=='SUCCESS')throw Error(obj.error||'노드 처리 실패');
 r.records.push({...obj,node_id:node.id});
 state.selectedNode=node.id;
 if(r.records.length===r.workflow.nodes.length){
  r.status='COMPLETED';
  r.decision=obj.output_json?.decision||'결과 없음';
 }else r.status='PAUSED';
 render();
}
async function runAction(which){
 if(state.busy)return;
 state.busy=true;state.stopRequested=false;state.error='';
 try{
  const m=market(state.market);
  if(which==='start'||!state.run||state.run.market!==state.market||state.run.status==='COMPLETED'||
    state.run.status==='FAILED'||state.run.status==='STOPPED'){
   const wf=await loadWorkflow(m.key);
   state.run={market:m.key,path:m.flow,workflow:wf,records:[],workflowRunId:null,status:'RUNNING',decision:null};
  }
  const r=state.run;
  if(which==='start'&&r.records.length>0){state.run={...r,records:[],workflowRunId:null,status:'RUNNING'};}
  state.run.status='RUNNING';render();
  if(which==='all'){
   while(state.run.records.length<state.run.workflow.nodes.length&&!state.stopRequested)
    await executeOne(state.run);
  }else if(!state.stopRequested){
   await executeOne(state.run);
  }
  if(state.stopRequested)state.run.status='STOPPED';
  else if(state.run.records.length<state.run.workflow.nodes.length)state.run.status='PAUSED';
  else state.run.status='COMPLETED';
  await loadStatus();
  if(state.run.status==='COMPLETED')popup('3개 시장별 실제 Python 모의 계산·SQLite 저장 완료 · '+(state.run.decision||''));
 }catch(e){
  if(state.run)state.run.status=state.stopRequested?'STOPPED':'FAILED';
  state.error=e.message;popup('모의 실행 중단: '+e.message,true);
 }finally{state.busy=false;render();}
}
async function loadPastRun(runId){
 try{
  state.historyRun=await api('/api/procurement/console/run?workflow_run_id='+encodeURIComponent(runId));
  state.page='audit';updateRoute();render();popup('기록된 실행 '+state.historyRun.nodes.length+'개 노드 열기');
 }catch(e){popup('실행기록 조회 실패: '+e.message,true);}
}
function updateRoute(){const u=new URL(location.href);u.searchParams.set('section',state.page);history.replaceState(null,'',u.pathname+u.search);}
function gotoPage(p){if(!M.some(x=>x[0]===p))return;state.page=p;updateRoute();render();window.scrollTo(0,0);}
async function reload(){
 await Promise.all([loadHealth(),loadStatus(),loadManifest()]);
 state.lastRefresh=new Date().toISOString();render();
}
document.addEventListener('click',async e=>{
 const nav=e.target.closest('[data-page]');
 if(nav){e.preventDefault();gotoPage(nav.dataset.page);return;}
 const btn=e.target.closest('[data-action]');
 if(!btn)return;
 const a=btn.dataset.action;
 if(a==='goto-tests')return gotoPage('tests');
 if(a==='goto-opportunities')return gotoPage('opportunities');
 if(a==='goto-audit')return gotoPage('audit');
 if(a==='choose-market'){
  state.market=btn.dataset.market||'public';state.run=null;state.selectedNode=null;
  return gotoPage('tests');
 }
 if(a==='inspect-node'){state.selectedNode=btn.dataset.node;render();return;}
 if(a==='load-run')return loadPastRun(btn.dataset.run);
 if(a==='stop-run'){state.stopRequested=true;popup('현재 노드 처리 종료 후 중지');return;}
 if(a==='reset-run'){state.run=null;state.selectedNode=null;render();return;}
 if(a==='start-root')return runAction('start');
 if(a==='next-step')return runAction('next');
 if(a==='run-all')return runAction('all');
});
document.addEventListener('change',e=>{
 if(e.target.id==='market-select'){state.market=e.target.value;state.run=null;state.selectedNode=null;render();}
 if(e.target.id==='preference-select'){state.preference=e.target.value;state.run=null;render();}
});
document.addEventListener('input',e=>{
 if(e.target.id==='feature-filter'){
  state.featureFilter=e.target.value;
  const pos=e.target.selectionStart;
  render();
  const input=el('feature-filter');input?.focus();try{input?.setSelectionRange(pos,pos);}catch{}
 }
 if(e.target.id==='flow-search'){
  state.flowSearch=e.target.value;
  const pos=e.target.selectionStart;
  render();
  const input=el('flow-search');input?.focus();try{input?.setSelectionRange(pos,pos);}catch{}
 }
});
el('refresh-all').addEventListener('click',()=>reload().then(()=>popup('SQLite·Studio 상태 확인 완료')));
reload();
})();
