/* Public9 live execution center: real API data only, automatic G2B selection.
 * The UI visualizes true N01-N09 states; no staged result is fabricated.
 */
'use strict';
(function(){
 const FLOW='operations/PF00-public-nine-real.json';
 const STAGES=['최신 공고 수집·선정','공고·첨부 원본 다운로드','공고 공식 속성 수집','동일 세부품명 10년 공고 수집',
  '과거 개찰·낙찰 원본 수집','공급·인력 근거자료 수집','원가·가격 근거자료 수집','전체 수집자료 통합·AI 전달','AI 종합 분석·최종 평가'];
 const LABELS={verified:'검증 완료',running:'실행 중',partial:'부분 확인',blocked:'차단',
  source_error:'오류',not_executed:'미실행',waiting:'대기'};
 const PROBLEMS=['source_error','blocked','partial','not_executed'];
 const st={selectedNode:0,manualSelect:false,run:null,error:null,submitting:false,lastReload:null};
 let polling=false;
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const fmt=o=>esc(JSON.stringify(o??null,null,2));
 const id=i=>'N'+String(i+1).padStart(2,'0');
 const stage=i=>st.run?.steps?.find(x=>x.node===id(i));
 const name=i=>id(i)+' · '+STAGES[i];
 const live=()=>st.run?.status==='running';
 const activeIndex=()=>STAGES.findIndex((_,i)=>st.run?.active_node===id(i));
 const phase=i=>{const s=stage(i);return s?s.status:(live()&&activeIndex()===i?'running':'waiting');};
 const statusName=code=>LABELS[code]||code||'대기';
 const resultSteps=()=>st.run?.steps||[];
 const countOf=code=>resultSteps().filter(x=>x.status===code).length;
 const problemSteps=()=>resultSteps().filter(x=>PROBLEMS.includes(x.status));
 const clock=date=>{if(!date)return '--:--:--';try{return new Date(date).toLocaleTimeString('ko-KR',{timeZone:'Asia/Seoul',hour12:false});}catch(_){return String(date).slice(11,19);}};
 const duration=date=>{if(!date)return '0초';const seconds=Math.max(0,Math.floor((Date.now()-new Date(date).getTime())/1000));if(!Number.isFinite(seconds))return '시간 계산 불가';return seconds>=60?Math.floor(seconds/60)+'분 '+(seconds%60)+'초':seconds+'초';};
 const preview=(v,max=125)=>{const t=String(v??'').replace(/\s+/g,' ').trim();return t.length>max?t.slice(0,max-1)+'…':t;};
 function reason(s){
   if(!s)return '선행 노드 완료 대기';
   const out=s.output||{},gaps=out.gaps||out.collection_gaps||[];
   if(out.error)return String(out.error);
   if(s.node==='N01'&&s.status==='verified')return '공식 최신 미완료 공고 선정 · '+(out.bid_no||'');
   if(s.node==='N02'&&s.status==='verified')return '공식 원본 '+(out.file_count??out.downloaded??0)+'개 보관 · 내용 분석 없음';
   if(s.node==='N03')return out.detail10_verified?'공식 10자리 세부품명 '+out.detail10+' 확보 · 판단 없음':'공식 공고 속성 수집 · 10자리 세부품명 미확인';
   if(s.node==='N04')return '10년 조회 기간 '+(out.periods_checked?.length||0)+'개 구간 · 정확한 분류 연결 공고 '+(out.verified_record_count||0)+'건 · 평가 없음';
   if(s.node==='N05')return '과거 개찰 원본 '+(out.opening_records?.length||0)+'건 수집 · 개별 업체 평가 없음';
   if(s.node==='N06')return '공급·인력 관련 출처 목록 수집 · 누락 출처 '+gaps.length+'건';
   if(s.node==='N07')return '원가·가격 원본 필드 '+(out.source_amounts?.length||0)+'건 수집 · 추천가격 산출 없음';
   if(s.node==='N08')return '원본 '+(out.source_originals||0)+'개와 수집자료 통합 · AI 전달 준비';
   if(s.node==='N09'){
     if(out.ai_evaluation_performed)return '최종 AI 종합 보고서 생성 · 사람 검토 필요';
     return out.reason||'AI API 미설정 또는 최종 분석 미실행';
   }
   if(s.status==='source_error')return 'GitHub Actions 자료 수집 또는 저장 오류';
   if(s.status==='partial')return '일부 수집자료 미확인 · 다음 단계 수집은 계속';
   if(s.status==='blocked')return '필수 데이터가 확보되지 않아 단계 수행 불가';
   return '단계 결과 확인';
 }

 function syncFollow(){
   if(st.manualSelect)return;
   const a=activeIndex();
   if(a>=0){st.selectedNode=a;return;}
   const p=problemSteps()[0];
   if(st.run?.status!=='running'&&p){st.selectedNode=STAGES.findIndex((_,i)=>id(i)===p.node);return;}
   if(resultSteps().length)st.selectedNode=Math.min(8,resultSteps().length-1);
 }
 function renderView(){
   // Keep the SAME Vue Flow iframe alive while its sibling status regions refresh.
   // Rebuilding #content on each 1.8s poll would destroy drag/pan/editor state.
   const regions=document.querySelectorAll('[data-p9-region]');
   if(!regions.length){window.Public9?.requestRender?.();return;}
   const fragments={overview,inventory,issues,actions,inspector,audit};
   regions.forEach(region=>{
     const fn=fragments[region.getAttribute('data-p9-region')];
     if(fn)region.innerHTML=fn();
   });
   syncEmbeddedStudio();
   syncStudioControls();
 }
 function syncStudioControls(){
   // Never hide the start button. Keep its actual status visible *above*
   // the common Studio iframe during refreshes, without reloading the graph.
   const top=document.querySelector('[data-testid="live-nine-run-top"]');
   if(top){
     top.disabled=Boolean(st.submitting||live());
     top.textContent=st.submitting?'실행 요청 확인 중…':live()?'9단계 실행 중':'▶ 9단계 실행 시작';
   }
   const banner=document.querySelector('[data-p9-start-feedback]');
   if(banner){
     const unavailable=st.run?.dispatch_ready===false;
     const message=st.error||
       (unavailable?'GitHub Actions 실행 권한이 아직 연결되지 않았습니다. 실행 버튼을 누르면 서버에서 연결 상태를 확인하고 정확한 오류를 표시합니다.':'');
     banner.textContent=message;
     banner.hidden=!message;
   }
 }
 function syncEmbeddedStudio(){
   const frame=document.getElementById('p9-shared-studio-frame');
   if(!frame||!frame.contentWindow)return;
   frame.contentWindow.postMessage({
     type:'procureflow:live-nine-state',run:st.run,
     selectedNode:id(st.selectedNode),follow:!st.manualSelect
   },location.origin);
 }
 function showStudioFullscreen(open){
   const panel=document.getElementById('p9-shared-studio-panel');
   if(!panel)return;
   panel.classList.toggle('p9-studio-fullscreen',!!open);
   panel.setAttribute('role',open?'dialog':'region');
   panel.setAttribute('aria-modal',open?'true':'false');
   document.body.classList.toggle('p9-studio-modal-open',!!open);
   panel.querySelector('[data-public9="expand"]')?.setAttribute('aria-label',open?'전체 화면 닫기':'전체 화면 확대');
   panel.querySelector('[data-public9="expand"]')?.setAttribute('aria-expanded',String(!!open));
   panel.querySelector('[data-p9="studio-size"]')?.replaceChildren(document.createTextNode(open?'축소':'전체 화면'));
   if(open)panel.querySelector('[data-public9="expand"]')?.focus();
 }
 
 async function request(route,opts){
   const response=await fetch('/api/procurement/public9/'+route,{credentials:'same-origin',cache:'no-store',...opts});
   const data=await response.json().catch(()=>({error:'INVALID_JSON_RESPONSE'}));
   if(!response.ok)throw Error(data.error||'HTTP '+response.status);
   return data;
 }
 async function load(){
   try{st.run=await request('live-run');st.lastReload=new Date().toISOString();st.error=null;syncFollow();}
   catch(e){st.error=e.message;}
   renderView();
 }
 async function poll(){
   if(polling)return;
   polling=true;
   try{st.run=await request('live-run');st.error=null;st.lastReload=new Date().toISOString();syncFollow();}
   catch(e){st.error='상태 갱신 실패: '+e.message;}
   finally{polling=false;renderView();}
 }
 async function execute(){
   if(st.submitting||live())return;
   st.error=null;st.submitting=true;st.manualSelect=false;st.selectedNode=0;renderView();
   try{
     await request('live-run');
     st.run=await request('run-all',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:'auto'})});
     syncFollow();
   }catch(e){
     const missing=/GITHUB_DISPATCH_TOKEN_NOT_CONFIGURED|GITHUB_ACTIONS_DISPATCH_UNAVAILABLE/.test(e.message||'');
     st.error=missing
       ?'실행을 시작하지 못했습니다. Railway의 PROCUREFLOW_GITHUB_DISPATCH_TOKEN이 미설정되어 GitHub Actions에 작업을 요청할 권한이 없습니다. 인증정보를 등록한 뒤 다시 실행해 주십시오. Railway에서 크롤링을 대신 실행하지 않았습니다.'
       :'실행 요청 실패: '+e.message;
   }
   finally{st.submitting=false;renderView();}
 }
 function overview(){
   const r=st.run||{},completed=Math.min(9,r.completed_steps||0);
   const verified=countOf('verified'),issues=problemSteps(),current=activeIndex();
   const title=live()?(current>=0?name(current)+' 실행 중':'다음 노드 실행 준비 중'):
     (r.status==='not_run'||!r.run_id?'아직 실행되지 않았습니다':
       issues.length?'전체 수집 실행 종료 · 자료 확인 필요 '+issues.length+'개':'9단계 종료 · 최종 AI 결과 확인');
   const overall=live()?'running':!r.run_id?'waiting':issues.length?'partial':r.status==='failed'?'source_error':'verified';
   return '<section class="panel p9-overview" aria-label="9단계 전체 실행 현황">'+
    '<div class="p9-overview-heading"><div><div class="p9-eyebrow">실시간 실행 현황 · LIVE EXECUTION</div>'+
    '<h3 data-p9="headline">'+esc(title)+'</h3></div>'+
    '<span class="p9-status-pill p9-'+overall+'" data-p9="global-status" role="status">'+
    (live()?'<span class="p9-pulse" aria-hidden="true"></span>':'')+
    esc(live()?'진행 중':r.status==='not_run'||!r.run_id?'대기':r.status==='completed_with_missing_evidence'?'수집 누락·AI 확인 필요':r.status==='failed'?'실행 실패':r.status==='completed'?'전체 완료':'종료')+'</span></div>'+
    '<div class="p9-progress-top"><strong data-p9="counter">진행된 단계 '+completed+' / 9</strong>'+
    '<span>완료 <b>'+verified+'</b> · 자료 일부 확인 <b>'+countOf('partial')+'</b> · 차단 <b>'+countOf('blocked')+
    '</b> · 오류 <b>'+countOf('source_error')+'</b></span></div>'+
    '<div class="p9-progress-track" role="progressbar" aria-label="9단계 실행 진행률" aria-valuemin="0" aria-valuemax="9" aria-valuenow="'+completed+'">'+
    '<div class="p9-progress-fill" style="width:'+(completed/9*100).toFixed(2)+'%"></div></div>'+
    '<div class="p9-overview-foot"><span>'+(r.case_bid_no?'선택 공고 <b>'+esc(r.case_bid_no)+'-'+esc(r.case_bid_ord||'000')+'</b>':'공고번호 자동 선택 대기')+'</span>'+
    '<span>'+(live()?'현재 단계 소요 <b data-p9-elapsed="'+esc(r.active_since||'')+'">'+esc(duration(r.active_since))+'</b>':
       r.finished_at?'종료 시각 '+esc(clock(r.finished_at)):'실행 전')+'</span></div>'+
    '<p class="p9-helper">N01~N08은 자료 수집·정리만 수행합니다. 입찰 관련 판단과 AI 평가는 N09에서만 수행합니다.</p></section>';
 }
 function studio(){
   const src='/?workflow='+encodeURIComponent(FLOW)+'&public9_embed=1';
   return '<section class="panel p9-studio-panel" id="p9-shared-studio-panel" data-p9-studio-panel role="region" aria-label="공용 Studio 실시간 노드 관리 화면">'+
     '<div class="p9-panel-heading p9-studio-toolbar"><div><h3>공용 n8n Studio · 노드 관리 및 실시간 실행</h3>'+
     '<p>기존 공용 노드 편집기입니다. 노드를 선택하거나 캔버스를 드래그하실 수 있으며, 실행상태가 노드에 직접 반영됩니다.</p></div>'+
     '<div class="p9-studio-toolbar-actions">'+
     '<button class="btn primary" type="button" data-public9="run" data-testid="live-nine-run-top" '+((st.submitting||live())?'disabled':'')+'>'+
       (st.submitting?'실행 요청 확인 중…':live()?'9단계 실행 중':'▶ 9단계 실행 시작')+'</button>'+
     '<button class="btn" type="button" data-public9="follow" aria-pressed="'+(!st.manualSelect?'true':'false')+'">'+
      (st.manualSelect?'현재 단계 다시 추적':'자동 추적 중')+'</button>'+
     '<button class="btn primary" type="button" data-public9="expand" aria-expanded="false" aria-label="전체 화면 확대">'+
     '<span data-p9="studio-size">전체 화면</span></button></div></div>'+
     '<p class="p9-start-feedback" data-p9-start-feedback role="alert" '+((st.error||st.run?.dispatch_ready===false)?'':'hidden')+'>'+
       esc(st.error||(st.run?.dispatch_ready===false?'GitHub Actions 실행 권한이 아직 연결되지 않았습니다. 실행 버튼을 누르면 서버에서 연결 상태를 확인하고 정확한 오류를 표시합니다.':''))+'</p>'+
     '<iframe id="p9-shared-studio-frame" data-testid="public9-shared-studio" title="기존 공용 n8n Studio 편집기 · 9개 실시간 실행 노드" loading="eager" src="'+src+'" allow="clipboard-write"></iframe>'+
     '<p class="p9-helper">현재 실행 중인 노드는 강조 표시되며, 차단·부분 확인·오류는 노드 자체에 표시됩니다. 확대해도 같은 캔버스가 유지됩니다.</p>'+
     '</section>';
 }
  function inventory(){
   const out=stage(1)?.output;
   const files=Array.isArray(out?.files)?out.files:[];
   if(!out)return '';
   const total=out?.file_count??files.length;
   const complete=out.official_attachment_inventory_complete===true;
   const rows=files.map(file=>'<li class="p9-inventory-item">'+
     '<div class="p9-inventory-file"><span class="p9-inventory-seq">'+
     String(file.file_seq||'').padStart(2,'0')+'</span><strong>'+esc(file.original_filename||'이름 미확인')+'</strong></div>'+
     '<div class="p9-inventory-meta"><span>'+esc((file.file_type||'기타').toUpperCase())+'</span>'+
     '<span>'+esc(file.size_bytes?((file.size_bytes/1024).toFixed(1)+' KB'):'크기 미확인')+'</span>'+
     '<span>'+(file.saved?'<span class="p9-inventory-saved">원본 저장됨</span>':'저장 실패')+'</span></div>'+
     '<div class="p9-inventory-path" title="'+esc(file.saved_path||'')+'">'+esc(file.saved_path||'저장 경로 미확인')+'</div>'+
   '</li>').join('');
   return '<section class="panel p9-inventory" aria-label="공고 첨부 원본 파일 저장 목록">'+
     '<div class="p9-panel-heading"><div><h3>N02 · 공고 원본 파일 보관함</h3>'+
     '<p>파일명과 유형을 기준으로 선별하지 않고, 공식 서버에서 발견한 원본을 모두 저장합니다.</p></div>'+
     '<span class="p9-status-pill '+(complete?'p9-verified':'p9-partial')+'">'+
     esc(complete?'첨부 수집 종료 확인':'수집 일부 미확인')+'</span></div>'+
     '<p class="p9-inventory-summary"><strong>'+esc(total)+'개 파일</strong> · 총 '+esc(((out.total_bytes||0)/1024/1024).toFixed(2))+
     ' MB · <span>내용 분석 없이 원본만 보관</span></p>'+
     (files.length?'<ul class="p9-inventory-list">'+rows+'</ul>':'<p>아직 저장된 원본 파일이 없습니다.</p>')+
     '<p class="p9-inventory-folder"><b>공고별 보관 폴더</b> <code>'+esc(out.storage_folder||'--')+'</code></p>'+
     '<p class="p9-inventory-folder"><b>평가 단계 전달 목록</b> <code>'+esc(out.manifest_path||'--')+'</code></p>'+
     (!complete?'<p class="p9-helper">파일 수집 완료 여부가 확인되지 않았습니다. 실패나 누락을 원문 파일 수집 완료로 취급하지 않습니다.</p>':'')+
     '</section>';
 }
 function issues(){
   const entries=problemSteps();
   if(!entries.length&&live())return '<section class="panel p9-issues"><h3>문제 감지</h3><p class="p9-clear">현재까지 보고된 오류·차단·부분 확인이 없습니다. 실행은 진행 중입니다.</p></section>';
   if(!entries.length)return '<section class="panel p9-issues"><h3>문제 감지</h3><p class="p9-clear">'+
     (st.run?.run_id?'기록된 오류·차단·부분 확인이 없습니다.':'아직 실행 기록이 없습니다.')+'</p></section>';
   return '<section class="panel p9-issues" aria-label="확인 필요한 노드">'+
     '<div class="p9-panel-heading"><div><h3>수집 누락·확인할 항목 <span class="p9-issue-count">'+entries.length+'개</span></h3>'+
     '<p>수집 누락·오류와 최종 AI 평가 미실행 사유를 확인할 수 있습니다.</p></div></div>'+
     '<div class="p9-issue-list">'+entries.map(s=>{
       const i=Number(s.node.slice(1))-1;
       return '<button class="p9-issue-row p9-'+esc(s.status)+'" type="button" data-public9="node" data-index="'+i+'">'+
       '<span class="p9-issue-id">'+esc(s.node)+'</span>'+
       '<span class="p9-issue-text"><b>'+esc(STAGES[i]||s.title)+'</b><small>'+esc(preview(reason(s),210))+'</small></span>'+
       '<span class="p9-state">'+esc(statusName(s.status))+'</span></button>';
     }).join('')+'</div>'+
     (live()?'<p class="p9-helper">수집 누락은 그대로 기록하며 후속 수집을 중단하지 않습니다. 판단과 평가는 N09에서만 수행합니다.</p>':'')+
     '</section>';
 }
 function inspector(){
   const i=st.selectedNode,s=stage(i),v=phase(i),r=st.run||{};
   return '<section class="panel p9-inspector" aria-label="선택 노드 상세 정보">'+
    '<div class="p9-panel-heading"><div><h3>선택 노드 실행 상세 · '+esc(name(i))+'</h3>'+
    '<p>공용 Studio 노드 또는 수집 누락 목록에서 원하는 노드를 선택하실 수 있습니다.</p></div>'+
    '<span class="p9-status-pill p9-'+esc(v)+'">'+esc(statusName(v))+'</span></div>'+
    (s?'<p class="p9-inspector-reason">'+esc(reason(s))+'</p>'+
      '<div class="p9-detail-meta"><span>완료 시각 '+esc(clock(s.at))+'</span><span>공고 '+esc(r.case_bid_no||'아직 자동 선택되지 않음')+'</span>'+ (s.github_run_id && /^\d+$/.test(String(s.github_run_id))?'<span><a target="_blank" rel="noopener" href="https://github.com/lyonbegin/procureflow/actions/runs/'+esc(s.github_run_id)+'">Actions 실행 로그 ↗</a></span>':'')+'</div>'+
      '<div class="p9-detail-grid"><div><h4>실제 INPUT</h4><pre class="log">'+fmt(s.input)+'</pre></div>'+
      '<div><h4>실제 OUTPUT</h4><pre class="log">'+fmt(s.output)+'</pre></div></div>':
      '<div class="p9-inspector-idle">'+(v==='running'?'현재 GitHub Actions에서 해당 노드를 실행 중입니다. 결과가 반환되면 자동 갱신됩니다.':'아직 실행되지 않았습니다.')+'</div>')+
    '</section>';
 }
 function audit(){
   const r=st.run||{},events=resultSteps().slice(-5).reverse();
   return '<section class="panel p9-audit" aria-label="실행 이벤트 기록">'+
     '<div class="p9-panel-heading"><div><h3>최근 단계 전환</h3><p>서버가 기록한 노드 종료 결과입니다.</p></div>'+
     '<span class="p9-poll-indicator">'+(st.error?'상태 갱신 오류':live()?'1.8초 간격 자동 갱신':'마지막 기록 표시')+'</span></div>'+
     (events.length?'<ul class="p9-events">'+events.map(s=>'<li>'+
        '<time>'+esc(clock(s.at))+'</time><b>'+esc(s.node)+'</b><span>'+esc(statusName(s.status))+'</span>'+
        '<small>'+esc(preview(reason(s),96))+'</small></li>').join('')+'</ul>':
        '<div class="p9-inspector-idle">첫 단계가 끝나면 전환 기록이 표시됩니다.</div>')+
     '<div class="p9-audit-footer">'+
     (r.run_id?'<span>실행 ID <code>'+esc(r.run_id)+'</code></span>':'<span>실행 기록 없음</span>')+
     '<span>마지막 수신 '+esc(clock(st.lastReload))+'</span></div></section>';
 }
 function actions(){
   return '<section class="panel p9-controls">'+
      '<div class="p9-panel-heading"><div><h3>최신 미완료 공고 자동 실행</h3>'+
      '<p>N01~N08에서 가능한 자료를 수집·보관하고, N09에서만 AI가 분석합니다. 아직 누락된 공고는 재처리합니다.</p></div></div>'+
      '<div class="actions">'+
      '<button class="btn primary" data-public9="run" data-testid="live-nine-run-all" '+((st.submitting||live())?'disabled':'')+
      '>▶ 최신 미완료 공고 자동 선정 · 9개 실행</button>'+
      '<button class="btn" data-public9="latest">진행 상태 새로고침</button>'+
      '<button class="btn" data-public9="open">공용 노드 캔버스 전체 화면</button></div>'+
      '<p class="p9-helper">실행 버튼은 개별 GitHub Actions 노드를 순서대로 요청합니다. Railway는 UI·상태·원본 보관만 담당합니다. 중간 평가·자동 투찰은 수행하지 않습니다.</p>'+
      (st.run?.dispatch_ready===false?'<div class="notice warn" role="alert">현재 인증정보가 없어 실제 실행은 실패할 수 있습니다. 버튼을 누르면 실제 실행 요청을 보내고, 실패 시 화면 상단에 원인을 안내합니다. Railway 자체 크롤링으로 대체하지 않습니다.</div>':'')+
      (st.error?'<div class="notice warn" role="alert">'+esc(st.error)+'</div>':'')+
      (st.run?.error?'<div class="notice warn" role="alert">서버 실행 오류: '+esc(st.run.error)+'</div>':'')+
      (stage(8)?.output?.ai_evaluation_performed?'<p class="p9-helper">N09 AI 보고서는 N09 노드를 선택해 OUTPUT에서 확인하실 수 있습니다. 최종 입찰참가 승인과 자동 투찰은 수행하지 않습니다.</p>':'')+
     '</section>';
 }
 function region(which,fn){return '<div data-p9-region="'+which+'">'+fn()+'</div>';}
 function main(){
   return '<section class="hero p9-hero"><div class="kicker">PUBLIC · LIVE 9 STAGE TEST</div>'+
    '<h2>공식 나라장터 → 최신 미완료 공고 자동 선택 → 공용 Studio 실행 관제</h2>'+
    '<p>실행 진행상태가 별도 흐름도가 아닌 공용 노드 관리 캔버스에 직접 표시됩니다.</p></section>'+
    region('overview',overview)+region('actions',actions)+studio()+region('issues',issues)+
    region('inventory',inventory)+
    region('inspector',inspector)+region('audit',audit);
 }
 function nodes(){
   return '<section class="hero p9-hero"><div class="kicker">SHARED N8N STUDIO · LIVE</div>'+
    '<h2>공용 노드 관리 · 실제 실행상태</h2><p>별도 복제 흐름도 없이 기존 Vue Flow 캔버스를 그대로 표시합니다.</p></section>'+
    region('overview',overview)+region('actions',actions)+studio()+region('issues',issues)+
    region('inventory',inventory)+region('inspector',inspector)+region('audit',audit);
 }
 document.addEventListener('click',async ev=>{
   const el=ev.target.closest('[data-public9]');
   if(!el)return;
   ev.preventDefault();ev.stopPropagation();
   if(el.dataset.public9==='run')await execute();
   else if(el.dataset.public9==='latest')await poll();
   else if(el.dataset.public9==='open')showStudioFullscreen(true);
   else if(el.dataset.public9==='expand')showStudioFullscreen(!document.getElementById('p9-shared-studio-panel')?.classList.contains('p9-studio-fullscreen'));
   else if(el.dataset.public9==='node'){
     st.selectedNode=Math.max(0,Math.min(8,Number(el.dataset.index)||0));
     st.manualSelect=true;renderView();
   }else if(el.dataset.public9==='follow'){
     st.manualSelect=false;syncFollow();renderView();
     const panel=document.getElementById('p9-shared-studio-panel');
     if(panel)panel.querySelector('[data-public9="follow"]').textContent='자동 추적 중';
   }
 });
 window.addEventListener('message',evt=>{
   const frame=document.getElementById('p9-shared-studio-frame');
   if(evt.origin!==location.origin||!frame||evt.source!==frame.contentWindow)return;
   const data=evt.data;
   if(data?.type==='procureflow:studio-ready'){syncEmbeddedStudio();return;}
   if(data?.type==='procureflow:node-selected' && /^N0[1-9]$/.test(data.node)){
     st.selectedNode=Number(data.node.slice(1))-1;
     st.manualSelect=true;
     renderView();
   }
 });
 document.addEventListener('keydown',ev=>{
   if(ev.key==='Escape'&&document.getElementById('p9-shared-studio-panel')?.classList.contains('p9-studio-fullscreen')){
     ev.preventDefault();showStudioFullscreen(false);
   }
 });
 setInterval(()=>{if(document.visibilityState==='visible')void poll();},live()?1800:3000);
 setInterval(()=>{
   const elapsed=document.querySelector('[data-p9-elapsed]');
   if(elapsed&&live())elapsed.textContent=duration(elapsed.getAttribute('data-p9-elapsed'));
 },1000);
 window.Public9={render:main,renderNodes:nodes,load,state:st,syncEmbeddedStudio};
 load();
})();