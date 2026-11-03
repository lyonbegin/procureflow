/* Public procurement main command center: REAL newest notices → selected tender →
 * original Worker job → 9 stage DB run IDs → SAME-ORIGIN original Studio editor.
 * B/C remain untouched. No fictitious data, n8n execution claims or auto bidding.
 */
'use strict';
(function(){
const FLOW='operations/PF00-public-nine-real.json';
const CASE='R26BK01787028',DETAIL='8111159901';
const STAGES=[
['최신 공고 목록·선택','G2B DB의 공고번호·차수·신규/정정'],
['공고·첨부 원본 분석','기존 원본·HWP/PDF/XLSX 해시 재사용'],
['입찰참가 자격 검토','실제 회사 자격·원본 증빙'],
['과거 개찰·낙찰 필터검색','정확 10자리·기간·기관 검색'],
['경쟁업체·기관 분석','실제 참가업체·금액·순위'],
['수행계획·원가 산출','인력·원가·외주 증빙'],
['가격·수주전략 판단','기초금액·가격규칙·수익성'],
['입찰서류 작성','원본에 근거한 Word 검토 초안'],
['독립 검증·사람 승인','필수 자격·가격·서류 / 선택 공고 마감']
];
const API='/api/procurement/public9/';
const st={notices:null,selected:null,job:null,search:'',status:'all',
  error:null,loading:false,submitting:false,token:'',selectedNode:0,
  nodeTab:'result',lastReload:null,loadStarted:false};
const esc=v=>String(v===null||v===undefined?'':v).replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
const at=()=>window.location.search.includes('section=public_nodes')?'nodes':'main';
const asTime=v=>v?String(v).replace('T',' ').slice(0,19):'미확인';
const field=(name,val)=>'<span style="display:inline-flex;gap:5px;flex-wrap:wrap"><span class="muted">'+esc(name)+'</span><strong>'+esc(val)+'</strong></span>';
const label=(name,value)=>'<div class="item"><b>'+esc(name)+'</b><p>'+esc(value)+'</p></div>';
function refreshView(){
 const page=new URLSearchParams(location.search).get('section');
 if(page==='public_nodes'&&document.getElementById('p9-node-inspector')){
  // Preserve unsaved node editing in the original Studio iframe on every
  // Worker polling tick; only repaint the real run-result inspector.
  document.getElementById('p9-node-inspector').innerHTML=nodeInspector();
  return;
 }
 if(['public','public_nodes','overview','workflows','strategy','tests','audit','opportunities'].includes(page))
  window.dispatchEvent(new Event('public9-render'));
}
async function request(route,options){
 const r=await fetch(API+route,{credentials:'same-origin',cache:'no-store',...options});
 let result;try{result=await r.json()}catch{throw Error('실제 API에서 JSON 응답을 받지 못했습니다 ('+r.status+')')}
 if(!r.ok)throw Error(result.error||'API HTTP '+r.status);
 return result;
}
async function load(){
 if(st.loading)return;
 st.loading=true;st.error=null;refreshView();
 try{
  const [n,j]=await Promise.allSettled([
   request('notices?'+new URLSearchParams({q:st.search,status:st.status,limit:30,offset:0})),
   request('latest')]);
  if(n.status==='fulfilled'){
   if(n.value.source!=='actual_procureflow_postgresql_g2b_notices'||!Array.isArray(n.value.items))
    throw Error('모의 또는 확인되지 않은 공고 목록은 표시하지 않습니다');
   st.notices=n.value;
   const matches=st.notices.items.some(x=>x.bid_no===st.selected);
   if(!st.selected||!matches)st.selected=st.notices.items[0]?.bid_no||null;
  }else throw n.reason;
  if(j.status==='fulfilled'&&j.value.worker_job_id_is_not_n8n_execution_id===true){
   st.job=j.value;
  }else if(j.status==='fulfilled'&&j.value.job_state==='not_run'){
   st.job=j.value;
  }else{st.job=null;}
  st.lastReload=new Date().toISOString();
 }catch(e){st.error=e.message;}
 finally{st.loading=false;refreshView();}
}
async function poll(){
 try{
  const id=st.job?.job_id;
  if(!id)return;
  const job=await request('job/'+id);
  if(job.case_bid_no!==CASE||job.worker_job_id_is_not_n8n_execution_id!==true)
   throw Error('선택 공고 실제 실행기록 검증 실패');
  st.job=job;refreshView();
 }catch(e){st.error=e.message;refreshView();}
}
function tender(){return st.notices?.items?.find(x=>x.bid_no===st.selected)||null;}
function selectedReady(){return tender()?.can_run_full_evidence===true&&st.selected===CASE;}
function nodeRecords(){return st.job?.steps||[];}
function stageStatus(i){
 if(st.selected!==CASE)return '이 공고 실행 엔진 미연결';
 const x=nodeRecords()[i];return x?x.state:(st.job?.job_state==='queued'?'실행 대기':'미실행');
}
function main(){
 const items=st.notices?.items||[],t=tender();
 const waiting=st.loading?'<div class="loading">기존 G2B DB에서 실제 목록·실행이력 조회 중…</div>':'';
 const row=items.map((x,i)=>{
  const on=x.bid_no===st.selected;
  const supported=x.can_run_full_evidence===true;
  return '<tr style="'+(on?'background:rgba(76,142,202,.13)':'')+'">'+
   '<td><input type="radio" name="p9-tender" data-public9="choose" data-bid="'+esc(x.bid_no)+'" '+(on?'checked':'')+' aria-label="'+esc(x.bid_no)+' 선택"></td>'+
   '<td><b>'+esc(x.bid_no)+'</b><div class="muted smalltxt">'+esc(x.title)+'</div></td>'+
   '<td>'+esc(x.agency)+'</td><td>'+esc(asTime(x.notice_date))+'</td>'+
   '<td>'+esc(asTime(x.deadline))+'</td>'+
   '<td>'+ (supported?'<span class="badge ok">현재 실업무 연결</span>':'<span class="badge warn">실업무 연결 필요</span>')+'</td></tr>';
 }).join('');
 const chosen=t?'<div class="item"><b>'+esc(t.title)+'</b><p>'+esc(t.bid_no+'/'+(t.bid_ord||'000'))+
  ' · '+esc(t.agency)+' · 공고일 '+esc(t.notice_date)+' · 마감 '+esc(t.deadline)+'</p></div>':
  '<div class="empty">선택된 실제 공고가 없습니다.</div>';
 const current=st.job;
 const cards=STAGES.map(([name,desc],i)=>'<button class="btn small '+(st.selectedNode===i?'primary':'outline')+
  '" data-public9="node" data-index="'+i+'" style="text-align:left;flex:1 1 200px;min-width:185px;padding:12px">'+
  '<b>'+String(i+1).padStart(2,'0')+' · '+esc(name)+'</b><div class="muted smalltxt">'+esc(desc)+'</div>'+
  '<small>실제 상태: '+esc(stageStatus(i))+'</small></button>').join('');
 return (waiting||'')+
 '<section class="hero"><div class="kicker">PUBLIC · REAL ONE-TENDER COMMAND</div><h2>최신 공고 선택 → 전체 입찰 준비 실행 → 9개 노드·실제 이력·제출서류</h2>'+
 '<p>실제 PostgreSQL의 최신 나라장터 공고에서 선택합니다. 기존 Worker 실행 결과를 공유하며, 모의 완료율이나 가상의 낙찰가격을 표시하지 않습니다.</p></section>'+
 (st.error?'<div class="notice warn">실제 API 오류: '+esc(st.error)+' · 가상 목록으로 대체하지 않습니다.</div>':'')+
 '<section class="panel"><h3>① 나라장터 전체 최신 입찰공고 · 선택</h3>'+
 '<div class="actions"><input id="p9-q" class="input" placeholder="공고명 · 기관 · 공고번호 검색" maxlength="120" style="max-width:320px" value="'+esc(st.search)+'">'+
 '<select id="p9-status" class="select" style="max-width:170px">'+
 [['all','전체'],['open','마감 전'],['closed','마감 후']].map(([v,n])=>'<option value="'+v+'" '+(st.status===v?'selected':'')+'>'+n+'</option>').join('')+
 '</select><button data-public9="reload" class="btn small">↻ 실제 목록 조회</button></div>'+
 '<p class="muted smalltxt">저장된 공고 '+esc(st.notices?.total??'미확인')+'건 중 최신 30건 표시. 목록 갱신은 기존 G2B 수집기의 책임이며 조회 버튼은 새 크롤링을 시작하지 않습니다.</p>'+
 '<div class="table-wrap"><table><thead><tr><th>선택</th><th>실제 공고번호·제목</th><th>발주기관</th><th>게시</th><th>마감</th><th>실행 지원</th></tr></thead><tbody>'+
 (row||'<tr><td colspan="6">조건에 맞는 실제 수집 공고가 없습니다.</td></tr>')+
 '</tbody></table></div></section>'+
 '<section class="panel"><h3>② 선택 공고</h3>'+chosen+
 (selectedReady()?'<p class="muted smalltxt">실제 운영 엔진 대상 공고입니다. 다음 실행은 이 공고번호와 8111159901 분류를 사용합니다.</p>':
 '<div class="notice warn">이 공고는 목록에서 선택할 수 있지만 기존 단일공고 Worker가 아직 이 공고를 처리하도록 일반화되지 않았습니다. 잘못된 다른 공고로 고정 실행하지 않습니다.</div>')+
 '<div class="actions"><label class="label" style="min-width:210px">기존 관리자 토큰 (실행 시에만 사용)<input id="p9-token" class="input" type="password" autocomplete="off" placeholder="ADMIN_TOKEN"></label>'+
 '<button data-public9="run" class="btn primary" '+(!selectedReady()||st.submitting?'disabled':'')+'>▶ 선택 공고 전체 입찰 준비 실행</button>'+
 '<button data-public9="latest" class="btn">최근 실제 실행 기록 조회</button></div>'+
 '<p class="muted smalltxt">관리센터의 실행 버튼만 기존 Worker 작업을 등록합니다. 자동 투찰·전자서명·입찰참가 없음. 토큰은 저장하지 않습니다.</p></section>'+
 '<section class="panel"><h3>③ 동일 공고 9개 업무 노드</h3><div class="actions" style="gap:8px">'+cards+'</div>'+
 '<div class="actions"><button class="btn primary" data-page="public_nodes">선택 공고의 9노드 편집기 · 입력·출력 열기</button>'+
 '<button class="btn" data-public9="inspect">선택 단계의 실제 입력·출력 확인</button></div>'+
 nodeInspector()+'</section>'+
 '<section class="panel"><h3>④ 실제 Worker 실행 이력 · 경쟁·가격·제출서류</h3>'+
 (current?.job_id?label('실제 Worker 작업 ID '+current.job_id,'상태 '+current.job_state+
  ' · 기록 '+(current.actual_stages_recorded||0)+'/9 단계 · 공식 n8n Execution ID가 아님'):'<div class="empty">실제 Worker 실행 기록을 조회하지 못했습니다.</div>')+
 (current?.draft&&st.selected===CASE?'<div class="actions"><a class="btn primary" href="https://procureflow-api-production.up.railway.app/api/g2b/public/selected/prepare-jobs/'+current.job_id+
  '/draft.docx" target="_blank" rel="noopener">실제 근거 기반 Word 검토 초안 내려받기 · '+esc(current.draft.bytes)+' bytes</a></div>':'')+
 '<p class="muted smalltxt">자격·원가·확정 낙찰과 제출서식의 부족 여부는 각 노드 실행근거로 확인합니다. 완성된 투찰서가 아니라 검토 초안입니다.</p></section>';
}
function nodeInspector(){
 const i=st.selectedNode,found=nodeRecords()[i],name=STAGES[i][0];
 const html=found?
 '<p>'+field('업무',name)+'　'+field('DB 실제 run_id',found.run_id)+'　'+field('상태',found.state)+'</p>'+
 '<p class="muted smalltxt">시작 '+esc(asTime(found.started_at))+' · 종료 '+esc(asTime(found.finished_at))+'</p>'+
 (found.error?'<div class="notice warn">'+esc(found.error)+'</div>':'')+
 '<details open><summary>원본 Worker의 실제 처리 결과(JSON)</summary><pre class="log">'+esc(JSON.stringify(found.summary||{},null,2))+'</pre></details>':
 '<div class="empty">이 단계의 실제 DB 실행 이력이 없습니다. 다른 공고의 작업 기록으로 대체하지 않습니다.</div>';
 return '<div class="item"><b>선택 노드 '+(i+1)+' · '+esc(name)+'</b>'+html+'</div>';
}
function nodes(){
 const selected=tender();
 const path='/?workflow='+encodeURIComponent(FLOW);
 return '<section class="hero"><div class="kicker">PUBLIC9 / SAME ORIGINAL STUDIO EDITOR</div>'+
 '<h2>공공입찰 9개 업무 노드 관리</h2><p>관리센터와 같은 공고 '+esc(st.selected||'미선택')+
 ' · 기존 공용 Studio의 n8n 형식 노드를 저장·편집합니다. 실제 Worker의 단계 DB 이력은 아래에서 확인합니다.</p>'+
 '<div class="actions"><button class="btn primary" data-page="public">← 최신 공고·전체 실행 관리센터</button>'+
 '<a class="btn" href="'+path+'" target="_blank" rel="noopener">노드 편집기 새 창으로 열기 ↗</a></div></section>'+
 (!selectedReady()?'<div class="notice warn">선택 공고 '+esc(st.selected||'없음')+
 '의 실제 9단계 실행은 현재 기존 Worker에 미연결입니다. 이 편집기에서 다른 공고가 자동 실행되는 것은 아닙니다.</div>':'')+
 '<section class="panel"><h3>같은 공고의 9개 노드 · 실제 단계별 실행 이력</h3>'+
 '<div class="actions">'+STAGES.map(([n],i)=>'<button data-public9="node" data-index="'+i+
 '" class="btn small '+(st.selectedNode===i?'primary':'')+'">'+String(i+1).padStart(2,'0')+' '+esc(n)+
 ' / '+esc(stageStatus(i))+'</button>').join('')+'</div>'+nodeInspector()+'</section>'+
 '<section class="panel"><h3>공용 n8n Studio 실제 편집 캔버스 (동일 출처)</h3>'+
 '<p class="muted smalltxt">노드 이동·연결·설정·저장은 원래 공유 Studio의 기능입니다. 아래 그래프는 실제 운영 API 증빙 조회를 표현하며, 원본 Worker를 실행하는 버튼은 위 관리센터에 있습니다. 현재 Studio에서 변경한 노드 구성이 공식 n8n Worker 실행에 자동 배포되는 기능은 아직 미연결입니다.</p>'+
 '<iframe title="공공입찰 9개 업무 노드 공용 Studio 편집기" loading="lazy" src="'+path+
 '" style="display:block;width:100%;height:840px;border:1px solid #54708a;border-radius:12px;background:#0c1522"></iframe></section>';
}
async function execute(){
 if(!selectedReady())throw Error('현재 선택 공고의 실제 처리 Worker가 연결되지 않았습니다');
 const input=document.getElementById('p9-token');
 const token=input?.value.trim();
 if(!token)throw Error('기존 관리자 토큰을 입력해야 합니다');
 input.value='';
 st.submitting=true;refreshView();
 try{
  const v=await request('prepare',{method:'POST',headers:{"Content-Type":"application/json","Authorization":"Bearer "+token},
   body:JSON.stringify({bid_no:CASE,detail10:DETAIL,start:"2016-10-24",end:"2026-10-22",agency:""})});
  if(v.worker_source!=='g2b_public_prepare'||!v.job_id||v.bid_submitted!==false)
   throw Error('실제 기존 Worker 작업을 확인할 수 없습니다');
  st.job={job_id:v.job_id,case_bid_no:CASE,job_state:'queued',steps:[],actual_stages_recorded:0};
  refreshView();
  await poll();
 }finally{st.submitting=false;refreshView();}
}
document.addEventListener('click',async event=>{
 const hit=event.target.closest('[data-public9]');
 if(!hit)return;
 event.preventDefault();event.stopPropagation();
 const a=hit.dataset.public9;
 try{
  if(a==='choose'){st.selected=hit.dataset.bid;st.selectedNode=0;refreshView();}
  else if(a==='node'){st.selectedNode=Number(hit.dataset.index)||0;refreshView();}
  else if(a==='reload'){
   st.search=document.getElementById('p9-q')?.value||'';
   st.status=document.getElementById('p9-status')?.value||'all';
   await load();
  }else if(a==='latest'){await load();}
  else if(a==='inspect'){refreshView();}
  else if(a==='run'){await execute();}
 }catch(e){st.error=e.message;refreshView();}
});
setInterval(()=>{if(st.job?.job_id&&['queued','running'].includes(st.job.job_state))void poll();},5000);
window.Public9={render:main,renderNodes:nodes,load,state:st};
window.addEventListener('public9-render',()=>{if(window.Public9.requestRender)window.Public9.requestRender()});
load();
})();