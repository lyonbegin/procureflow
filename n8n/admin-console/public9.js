/* ProcureFlow direct-live nine-step TEST. No DB API, Worker, scheduler or mock.
 * All external official G2B calls are performed only by user's run click.
 */
'use strict';
(function(){
 const FLOW='operations/PF00-public-nine-real.json';
 const STAGES=['01 · 공고 직접 조회','02 · 첨부 원본 직접 다운로드',
  '03 · 자격·원문 조건','04 · 개찰 원본 직접 조회',
  '05 · 경쟁 정보 분석','06 · 수행·원가 근거',
  '07 · 가격전략 검증','08 · Word 검토 초안','09 · 독립 최종 검증'];
 const st={selectedNode:0,run:null,error:null,submitting:false,lastReload:null};
 let polling=false;
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const fmt=o=>esc(JSON.stringify(o??null,null,2));
 const stage=i=>st.run?.steps?.find(x=>x.node==='N'+String(i+1).padStart(2,'0'));
 function renderView(){if(window.Public9?.requestRender)window.Public9.requestRender();}
 async function request(route,opts){
   const r=await fetch('/api/procurement/public9/'+route,
    {credentials:'same-origin',cache:'no-store',...opts});
   const data=await r.json().catch(()=>({error:'INVALID_JSON_RESPONSE'}));
   if(!r.ok)throw Error(data.error||'HTTP '+r.status);
   return data;
 }
 async function load(){
   try{st.run=await request('live-run');st.lastReload=new Date().toISOString();st.error=null;}
   catch(e){st.error=e.message;}renderView();
 }
 async function poll(){
   if(polling)return;
   polling=true;
   try{
     const result=await request('live-run');
     st.run=result;renderView();
   }catch(e){st.error=e.message;renderView();}
   finally{polling=false;}
 }
 async function execute(){
   if(st.submitting||st.run?.status==='running')return;
   st.error=null;st.submitting=true;renderView();
   try{
     // GET establishes an isolated Studio cookie before the same-origin POST.
     await request('live-run');
     st.run=await request('run-all',{method:'POST',
       headers:{'Content-Type':'application/json'},
       body:JSON.stringify({mode:'auto'})});
   }catch(e){st.error=e.message;}
   finally{st.submitting=false;renderView();}
 }
 function inspector(){
   const i=st.selectedNode;const s=stage(i);
   return '<div class="item"><b>'+esc(STAGES[i])+'</b>'+
    (s?'<p><b>실행 상태: '+esc(s.status)+'</b> · '+esc(s.at)+'</p>'+
       '<p class="muted smalltxt">실제 INPUT</p><pre class="log">'+fmt(s.input)+'</pre>'+
       '<p class="muted smalltxt">실제 OUTPUT</p><pre class="log">'+fmt(s.output)+'</pre>'
      :'<p class="muted">이 노드는 아직 실행되지 않았습니다.</p>')+'</div>';
 }
 function progress(){
   return '<div class="actions" style="gap:8px;flex-wrap:wrap">'+
    STAGES.map((name,i)=>{
      const s=stage(i);const active=st.selectedNode===i;const inProgress=st.run?.status==='running'&&st.run?.active_node==='N'+String(i+1).padStart(2,'0');
      return '<button class="btn small '+(active?'primary':'outline')+
       '" data-public9="node" data-index="'+i+
       '" style="min-width:195px;flex:1 1 200px;text-align:left">'+
       esc(name)+'<div class="muted smalltxt">'+esc(inProgress?'실행 중 · '+(st.run.active_title||'공식 사이트 응답 대기'):s?.status||'대기')+'</div></button>';
    }).join('')+'</div>';
 }
 function runSummary(){
   const r=st.run||{};
   const selected=r.case_bid_no?'<p><b>자동 선택 공고: '+esc(r.case_bid_no)+'-'+esc(r.case_bid_ord||'000')+'</b> · '+esc(r.selection_reason||'')+'</p>':'<p>최신 미완료 공고를 서버에서 자동 선정합니다.</p>';
   const checkpoint=r.completion_checkpoint?'<p class="muted smalltxt">단계 완료 기록: '+esc(r.completion_checkpoint.verified_stage_count)+'/9 검증 완료 · '+esc(r.completion_checkpoint.state)+'</p>':'';
   return '<section class="panel"><h3>실제 수집 실행 기록</h3>'+selected+checkpoint+
    '<p>실행 모드: <b>'+esc(r.mode||'on_demand_live_no_database')+'</b> · 상태: <b>'+
    esc(r.status||'미실행')+'</b> · 완료 '+esc(r.completed_steps||0)+'/9 단계</p>'+
    (r.status==='running'&&r.active_node?'<p class="notice"><b>현재 실행 중: '+esc(r.active_node)+' · '+esc(r.active_title)+'</b> · 공식 사이트 응답/다운로드를 확인하고 있습니다.</p>':'')+
    '<p class="muted smalltxt">PostgreSQL 조회 0회 · 외부 Worker 호출 0회 · N01 공식 G2B 웹 목록 직접 POST · 자동 투찰 없음</p>'+
    (r.run_id?'<p class="muted smalltxt">테스트 실행 ID: '+esc(r.run_id)+'</p>':'')+
    (r.run_id&&stage(7)?.output?.draft_generated?
      '<p><a class="btn primary" href="/api/procurement/public9/live-docx?run_id='+encodeURIComponent(r.run_id)+
      '">원본 근거 기반 Word 테스트 초안 내려받기</a></p>':'')+
    (st.error?'<div class="notice warn">오류: '+esc(st.error)+'</div>':'')+
    (r.error?'<div class="notice warn">서버 실행 오류: '+esc(r.error)+'</div>':'')+
    '</section>';
 }
 function main(){
   return '<section class="hero"><div class="kicker">PUBLIC · LIVE 9 STAGE TEST</div>'+
    '<h2>최신 공고 자동 선정 → 완료여부 확인 → N02~N09 순차 실행</h2>'+
    '<p>기존 PostgreSQL을 조회하지 않고 공식 G2B에 새로 접속합니다. 서버에 Worker·스케줄러를 실행하지 않습니다.</p></section>'+
    '<section class="panel"><h3>① 최신 미완료 공고 자동 선택</h3><div class="item">'+
    '<b>사용자 선택 없음 · 공고번호 고정 없음</b><p>나라장터 최신 공고부터 확인합니다. 9단계가 모두 verified인 공고만 건너뛰며, 미완료 공고는 다시 선택합니다. 20건이 모두 완료됐다면 다음 페이지로 이동합니다.</p></div>'+
    '<div class="actions">'+
    '<button class="btn primary" data-public9="run" data-testid="live-nine-run-all" '+
    ((st.submitting||st.run?.status==='running')?'disabled':'')+
    '>▶ 최신 미완료 공고 자동 선정 · 9개 실행</button>'+
    '<button class="btn" data-public9="latest">진행 상태 새로고침</button>'+
    '<button class="btn" data-public9="open">공용 Studio에서 9개 노드 열기</button></div>'+
    '<p class="muted smalltxt">버튼은 자동 선정·실행을 검증하기 위한 수동 트리거입니다. 선택은 자동으로 수행하며, 이전 DB의 공고 데이터를 재활용하지 않습니다.</p></section>'+
    runSummary()+'<section class="panel"><h3>② 단계별 실행 · INPUT / OUTPUT</h3>'+
    progress()+inspector()+'</section>';
 }
 function nodes(){
   return '<section class="hero"><h2>공용 Studio · 9개 노드 직접 수집 실행</h2>'+
    '<p>사용자 공고 선택 없이, 실행 시 공식 나라장터 최신 목록에서 9단계 미완료 공고를 자동 선택합니다.</p></section>'+
    '<section class="panel"><div class="actions">'+
    '<button class="btn primary" data-page="public">관리센터 돌아가기</button>'+
    '<button class="btn" data-public9="open">새 창에서 캔버스 열기</button></div>'+
    '<iframe title="9개 업무 노드 편집기" loading="lazy" src="/?workflow='+encodeURIComponent(FLOW)+
    '" style="width:100%;height:850px;border:1px solid #54708a;border-radius:12px"></iframe></section>'+
    runSummary()+'<section class="panel"><h3>실제 실행 결과</h3>'+progress()+inspector()+'</section>';
 }
 document.addEventListener('click',async ev=>{
   const el=ev.target.closest('[data-public9]');
   if(!el)return;ev.preventDefault();ev.stopPropagation();
   if(el.dataset.public9==='run')await execute();
   else if(el.dataset.public9==='latest')await poll();
   else if(el.dataset.public9==='open')window.open('/?workflow='+encodeURIComponent(FLOW),'_blank','noopener');
   else if(el.dataset.public9==='node'){st.selectedNode=Number(el.dataset.index)||0;renderView();}
 });
 setInterval(()=>{if(st.run?.status==='running')void poll();},1800);
 window.Public9={render:main,renderNodes:nodes,load,state:st};
 load();
})();
