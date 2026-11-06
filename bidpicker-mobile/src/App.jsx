import React, {useState,useEffect,useCallback,useRef} from 'react';
import {
 House, Search, Bookmark, Bell, Settings, ChevronLeft,ChevronRight,
 SlidersHorizontal, Share2,MapPin,Clock, CalendarDays, Building2, Check,
 RefreshCw, Trash2, Plus, X, Info, ArrowRight, FileText, ExternalLink,
 AlertCircle, BellRing, Sparkles, Monitor, Paintbrush, Utensils,
 Wrench, GraduationCap, Package, MoreHorizontal, Globe2,
 Filter, ChevronDown, CheckCircle2, LayoutGrid, ShieldCheck
} from 'lucide-react';

const TABS=[
 {key:'home',text:'홈',Icon:House},{key:'search',text:'검색',Icon:Search},
 {key:'saved',text:'저장',Icon:Bookmark},{key:'alerts',text:'알림',Icon:Bell},
 {key:'settings',text:'설정',Icon:Settings}
];
const CATEGORIES=[
 {id:'it',text:'IT/소프트웨어',Icon:Monitor,emoji:'💻'},
 {id:'design',text:'디자인/인쇄',Icon:Paintbrush,emoji:'🎨'},
 {id:'food',text:'식품/급식/식자재',Icon:Utensils,emoji:'🍱'},
 {id:'cleaning',text:'청소/시설관리',Icon:Wrench,emoji:'🧹'},
 {id:'interior',text:'인테리어/공사',Icon:Wrench,emoji:'🛠️'},
 {id:'education',text:'교육/강의',Icon:GraduationCap,emoji:'📚'},
 {id:'office',text:'사무용품/납품',Icon:Package,emoji:'📦'},
 {id:'etc',text:'기타',Icon:MoreHorizontal,emoji:'🗂️'}
];
const REGIONS=['전국','서울','경기','인천','부산','대구','대전','광주','울산','세종','강원','충북','충남','전북','전남','경북','경남','제주'];
const TYPES=[{id:'',text:'전체'},{id:'GOODS',text:'물품'},{id:'SERVICE',text:'용역'},{id:'CONSTRUCTION',text:'공사'},{id:'FOREIGN',text:'외자'},{id:'ETC',text:'기타'}];
const SORTS=[{id:'latest',text:'최신순'},{id:'deadline',text:'마감임박순'},{id:'recommended',text:'추천순'}];
const API_ROOT='/api/bidpicker';

function useStored(key,initial) {
 const [data,setData]=useState(()=>{
  try{const saved=localStorage.getItem('bidpicker.original.'+key);return saved===null?initial:JSON.parse(saved)}catch{return initial}
 });
 useEffect(()=>{try{localStorage.setItem('bidpicker.original.'+key,JSON.stringify(data))}catch{}},[key,data]);
 return [data,setData];
}
function readRoute(){
 const raw=(location.hash||'#/home').slice(1).replace(/^\/+/,'');
 return raw||'home';
}
function asText(value){return value===null||value===undefined?'':String(value)}
function normalizeBid(b){
 if(!b||typeof b!=='object')return null;
 const id=asText(b.id||b.bid_no||b.bidNo),bidNo=asText(b.bidNo||b.bid_no),bidSeq=asText(b.bidSeq||b.bid_seq);
 const originalUrl=asText(b.originalUrl||b.original_url);
 return {
  id,bidNo,bidSeq,title:asText(b.title),status:asText(b.status),
  taskType:asText(b.taskType||b.task_type),agencyName:asText(b.agencyName||b.agency),
  demandAgencyName:asText(b.demandAgencyName||b.demand_agency),
  region:asText(b.region),postedAt:asText(b.postedAt||b.posted_at),
  deadlineAt:asText(b.deadlineAt||b.deadline_at),
  openingAt:asText(b.openingAt||b.opening_at),
  budgetAmount:asText(b.budgetAmount||b.budget),
  matchScore:b.matchScore??null,matchedKeywords:Array.isArray(b.matchedKeywords)?b.matchedKeywords:[],
  deadlineSoon:b.deadlineSoon===true,noticeKindName:asText(b.noticeKindName),
  bidMethodName:asText(b.bidMethodName),contractMethodName:asText(b.contractMethodName),
  summaryText:asText(b.summaryText),regionLimited:b.regionLimited===true,
  originalUrl,originalUrlConfirmed:b.original_url_confirmed_format===true||!!originalUrl
 };
}
function isSafeOriginalUrl(url){
 try{const u=new URL(url);return u.protocol==='https:' && (u.hostname==='g2b.go.kr'||u.hostname.endsWith('.g2b.go.kr'));}catch{return false}
}
function prettyPrice(raw){
 const n=Number(raw);
 if(!raw||!Number.isFinite(n))return '금액 미정';
 if(n>=100000000)return (n/100000000).toLocaleString('ko-KR',{maximumFractionDigits:1})+'억원';
 if(n>=10000)return Math.floor(n/10000).toLocaleString('ko-KR')+'만원';
 return n.toLocaleString('ko-KR')+'원';
}
function prettyDay(v){
 if(!v)return '마감일 미정';
 const d=new Date(v);if(Number.isNaN(d.getTime()))return v;
 return (d.getMonth()+1)+'월 '+d.getDate()+'일';
}
function typeLabel(t){return ({GOODS:'물품',SERVICE:'용역',CONSTRUCTION:'공사',FOREIGN:'외자',ETC:'기타'})[t]||'입찰공고'}
function getError(status){
 if(status===502||status===503)return '우리 나라장터 수집 FastAPI에 연결할 수 없습니다. 서버 상태를 확인해 주세요.';
 if(status===429)return '나라장터 데이터 조회 요청이 많습니다. 잠시 후 재시도해 주세요.';
 if(status===400)return '검색 조건을 확인해 주세요.';
 return '우리 나라장터 수집 서버 오류: HTTP '+String(status||'알 수 없음')+'.';
}

function Chip({active=false,children,onClick,subtle=false}){
 return <button type="button" onClick={onClick} className={'chip '+(active?'active ':'')+(subtle?'subtle':'')}>{active&&<Check size={12} strokeWidth={3}/>} {children}</button>;
}
function EmptyState({Icon=FileText,title,body,action,actionText}){
 return <div className="empty-state"><span className="empty-ico"><Icon size={28} strokeWidth={1.7}/></span><h3>{title}</h3><p>{body}</p>{action&&<button className="small-action" type="button" onClick={action}>{actionText||'다시 시도'}</button>}</div>;
}
function StatusChip({bid}){
 const urgent=bid.deadlineSoon||bid.status==='SOON';
 const unknown=!urgent&&!['OPEN','CLOSED'].includes(bid.status);
 return <span className={'status-chip '+(urgent?'urgent':bid.status==='CLOSED'?'closed':'')}><Clock size={11}/>{urgent?'마감 임박':bid.status==='CLOSED'?'마감':unknown?'상태 확인중':'공고중'}</span>;
}
function BidCard({bid,onOpen,saved,onSave}){
 if(!bid)return null;
 return <article className="bid-card" onClick={()=>onOpen(bid)} role="button" tabIndex={0} onKeyDown={e=>e.key==='Enter'&&onOpen(bid)}>
 <div className="bid-badges"><span className="kind-label">{typeLabel(bid.taskType)}</span>{bid.region&&<span className="minor-label">{bid.region}</span>}<span className="badge-spacer"/><StatusChip bid={bid}/></div>
 <h3>{bid.title||'제목 없음'}</h3>
 <p className="agency">{bid.agencyName||'공고기관 미확인'}</p>
 <div className="meta-line"><span><MapPin size={12}/>{bid.region||'지역 미확인'}</span><span className="meta-price">{prettyPrice(bid.budgetAmount)}</span><span className="meta-deadline">{prettyDay(bid.deadlineAt)}</span></div>
 {bid.matchedKeywords?.length>0&&<div className="keyword-strip">{bid.matchedKeywords.slice(0,3).map(x=><span key={x}>#{x}</span>)}</div>}
 {onSave&&<button type="button" className="card-save" aria-label={saved?'저장 해제':'공고 저장'} onClick={e=>{e.stopPropagation();onSave(bid)}}><Bookmark size={18} fill={saved?'#087f9c':'none'} strokeWidth={1.8}/></button>}
 </article>;
}

function PageHeader({title,onBack,actions,center=false}){
 return <div className={'page-header '+(center?'center':'')}>
 {onBack?<button type="button" className="icon-button" aria-label="뒤로" onClick={onBack}><ChevronLeft size={24}/></button>:<span className="left-spacer"/>}
 <h1>{title}</h1><div className="header-actions">{actions||<span className="right-spacer"/>}</div>
 </div>;
}
function BottomNav({tab,onNavigate,savedCount}){
 return <nav className="bottom-nav" aria-label="하단 메뉴">{TABS.map(({key,text,Icon})=><button key={key} className={'bottom-item '+(tab===key?'selected':'')} onClick={()=>onNavigate(key)} type="button"><Icon size={21} strokeWidth={tab===key?2.4:1.8} fill={tab===key&&key==='saved'?'#0b84a1':'none'}/><span>{text}</span>{key==='saved'&&savedCount>0&&<i/>}</button>)}</nav>
}
function InlineNotice({children,tone='info'}){
 return <div className={'inline-notice '+tone}><Info size={15}/><div>{children}</div></div>
}
function SectionHeading({title,link,action}){
 return <div className="section-heading"><h2>{title}</h2>{link&&<button type="button" onClick={action}>{link} <ChevronRight size={14}/></button>}</div>
}
function Popup({title,children,onClose,footer,small=false}){
 return <div className="overlay" onMouseDown={e=>e.target===e.currentTarget&&onClose()}>
 <div className={'popup '+(small?'popup-small':'')} role="dialog" aria-modal="true">
 <div className="popup-head"><h2>{title}</h2><button className="icon-button" onClick={onClose} aria-label="닫기"><X size={20}/></button></div>
 <div className="popup-body">{children}</div>{footer&&<div className="popup-actions">{footer}</div>}
 </div></div>;
}
function App(){
 const [route,setRoute]=useState(readRoute);
 const [onboarded,setOnboarded]=useStored('onboarding.completed',false);
 const [step,setStep]=useState(0);
 const [favorites,setFavorites]=useStored('saved.bidsJson',[]);
 const [recent,setRecent]=useStored('recent.searchesJson',[]);
 const [interestCats,setInterestCats]=useStored('interest.categories',[]);
 const [interestRegion,setInterestRegion]=useStored('interest.region','전국');
 const [alertRules,setAlertRules]=useStored('local.alert.conditions',[]);
 const [query,setQuery]=useState({keyword:'',category:'',region:'전국',taskType:'',deadlineSoon:false,includeClosed:false,sort:'latest',page:1,size:10});
 const [results,setResults]=useState([]);
 const [resultsMeta,setResultsMeta]=useState(null);
 const [searchError,setSearchError]=useState('');
 const [loading,setLoading]=useState(false);
 const [requestStarted,setRequestStarted]=useState(false);
 const [detailBid,setDetailBid]=useState(null);
 const [popup,setPopup]=useState('');
 const [previewNotice,setPreviewNotice]=useState('');
 const [status,setStatus]=useState(null);
 const [alertsForm,setAlertsForm]=useState({label:'',keyword:'',category:'',region:'전국',taskType:''});
 const [filter,setFilter]=useState(query);
 const [categoriesTemp,setCategoriesTemp]=useState([]);
 const [activeOnboard,setActiveOnboard]=useState(false);
 const [prefetched,setPrefetched]=useState(false);
 const [homeLatest,setHomeLatest]=useState([]);
 const inputRef=useRef(null);
 const mainScroll=useRef(null);
 const tab=route.split('/')[0];
 const isSub=!TABS.some(x=>x.key===tab);

 useEffect(()=>{const handler=()=>setRoute(readRoute());window.addEventListener('hashchange',handler);if(!location.hash)location.replace('#/home');return()=>window.removeEventListener('hashchange',handler)},[]);
 const go=useCallback((next)=>{location.hash='/'+next;if(mainScroll.current)mainScroll.current.scrollTop=0;setPopup('')},[]);
 const back=()=>{if(tab==='detail')go('search');else go('settings')};
 const [saved,setSaved]=[Array.isArray(favorites)?favorites:[],setFavorites];
 const keyOf=(b)=>asText(b?.id||b?.bidNo)+'#'+asText(b?.bidSeq);
 const isSaved=(b)=>saved.some(x=>keyOf(x)===keyOf(b));
 function toggleSave(b){setSaved(prev=>{const arr=Array.isArray(prev)?prev:[];return arr.some(x=>keyOf(x)===keyOf(b))?arr.filter(x=>keyOf(x)!==keyOf(b)):[{...b,savedAt:new Date().toISOString()},...arr].slice(0,500)})}
 function openDetail(b){
  setDetailBid(b);try{sessionStorage.setItem('bidpicker.detail',JSON.stringify(b))}catch{}
  go('detail/'+encodeURIComponent(b.id||b.bidNo));
  if(b.bidNo&&b.bidSeq){
   fetch(API_ROOT+'/detail/'+encodeURIComponent(b.bidNo)+'/'+encodeURIComponent(b.bidSeq))
    .then(r=>r.ok?r.json():null)
    .then(data=>{if(data?.item){const verified=normalizeBid(data.item);if(verified)setDetailBid(verified);}})
    .catch(()=>{});
  }
 }
 useEffect(()=>{if(tab==='detail'&&!detailBid){try{const b=JSON.parse(sessionStorage.getItem('bidpicker.detail')||'null');if(b)setDetailBid(b)}catch{}}},[tab,detailBid]);
 useEffect(()=>{if(tab==='interest_categories')setCategoriesTemp(Array.isArray(interestCats)?interestCats:[])},[tab]);
 useEffect(()=>{fetch(API_ROOT+'/status').then(async r=>r.ok?await r.json():null).then(setStatus).catch(()=>{})},[]);
 useEffect(()=>{
  let live=true;
  fetch(API_ROOT+'/discover?page=1&size=4&include_closed=true')
   .then(r=>r.ok?r.json():null)
   .then(data=>{if(live&&Array.isArray(data?.items))setHomeLatest(data.items.map(normalizeBid).filter(Boolean));})
   .catch(()=>{});
  return ()=>{live=false};
 },[]);

 async function load(queryValue,extend=false){
  if(loading)return;
  setLoading(true);setSearchError('');setRequestStarted(true);
  const q={...queryValue,region:queryValue.region==='전국'?'':queryValue.region};
  const params=new URLSearchParams();
  for(const [name,val] of Object.entries(q)){
   const apiKey=name==='taskType'?'task_type':name==='deadlineSoon'?'deadline_soon':name==='includeClosed'?'include_closed':name;
   if(val!==''&&val!==null&&val!==undefined)params.set(apiKey,String(val));
  }
  try{
   const r=await fetch(API_ROOT+'/discover?'+params.toString(),{headers:{Accept:'application/json'}});
   if(!r.ok)throw Error(String(r.status));
   const data=await r.json();
   const incoming=Array.isArray(data.items)?data.items.map(normalizeBid).filter(Boolean):[];
   if(!Array.isArray(data.items))throw Error('502');
   setResults(prev=>extend?[...prev,...incoming]:incoming);
   setResultsMeta({total:typeof data.total==='number'?data.total:incoming.length,hasMore:data.hasMore===true,loaded:incoming.length,filterNotes:Array.isArray(data.filterNotes)?data.filterNotes:[],source:data.source||''});
  }catch(e){setSearchError(getError(Number(e.message)||502));if(!extend){setResults([]);setResultsMeta(null);}}
  finally{setLoading(false)}
 }
 function runSearch(options={}){const next={...query,...options,page:1};setQuery(next);if(next.keyword.trim())setRecent(prev=>[next.keyword.trim(),...(Array.isArray(prev)?prev:[]).filter(x=>x!==next.keyword.trim())].slice(0,10));go('search');load(next)}
 function switchSort(sort){const next={...query,sort,page:1};setQuery(next);setPopup('');load(next)}
 function applyFilters(){const next={...filter,page:1};setQuery(next);setPopup('');load(next)}
 function openFilter(){setFilter({...query});setPopup('filters')}
 function clearFilter(){setFilter({keyword:query.keyword,category:'',region:'전국',taskType:'',deadlineSoon:false,includeClosed:false,sort:'latest',page:1,size:10})}
 function loadNext(){if(!resultsMeta?.hasMore||loading)return;const next={...query,page:query.page+1};setQuery(next);load(next,true)}
 function selectCategory(id){runSearch({category:id,...(tab==='home'?{keyword:'',region:'전국'}:{})})}
 function selectRegion(r){runSearch({region:r,...(tab==='home'?{keyword:'',category:''}:{})})}
 function saveRule(){
  const k=alertsForm.keyword.trim();if(!k&&!alertsForm.category&&!alertsForm.taskType&&(!alertsForm.region||alertsForm.region==='전국')){setPreviewNotice('키워드나 업종·지역·업무구분 중 하나 이상을 골라 주세요.');return}
  setAlertRules(prev=>[...prev,{...alertsForm,id:Date.now(),localOnly:true,label:alertsForm.label.trim()||alertsForm.keyword.trim()||'맞춤 조건'}]);setPopup('');setAlertsForm({label:'',keyword:'',category:'',region:'전국',taskType:''});setPreviewNotice('');
 }
 async function share(b){
  const url=isSafeOriginalUrl(b.originalUrl)?b.originalUrl:location.href;
  try{if(navigator.share)await navigator.share({title:b.title,url});else if(navigator.clipboard)await navigator.clipboard.writeText(url)}catch{}
 }
 const actualDetail=detailBid||saved.find(x=>x.id===decodeURIComponent(route.split('/').slice(1).join('/')||''))||null;
 const categoryName=(id)=>CATEGORIES.find(x=>x.id===id)?.text||'전체';
 const countText=(resultsMeta?.total??results.length)+'건';
 function Onboarding(){
  const slides=[
   {icon:LayoutGrid,title:'내 업종 공고만 쏙',description:'IT·청소·급식·인쇄·공사·교육·납품… 업종을 고르면 나라장터 공고 중 나에게 맞는 것만 모아서 보여드려요.'},
   {icon:BellRing,title:'마감 임박·추천을 놓치지 않게',description:'마감이 가까운 공고와 내 키워드에 맞는 추천 공고를 한눈에. 마감일과 추천 점수를 카드로 깔끔하게 보여드려요.'},
   {icon:Bookmark,title:'관심 공고 저장 · 원문 바로가기',description:'마음에 드는 공고는 저장해 두고, 원문 공고로 바로 이동해 자격요건을 확인하세요. 모두 무료입니다.'}
  ];const s=slides[step];const Icon=s.icon;return <div className="onboard-cover"><div className="onboard-top"><span>입찰공고 알리미</span><button onClick={()=>setOnboarded(true)}>건너뛰기</button></div><div className="onboard-content"><div className="onboard-symbol"><Icon size={44}/></div><h1>{s.title}</h1><p>{s.description}</p><div className="onboard-dots">{slides.map((_,i)=><span key={i} className={i===step?'on':''}/>)}</div></div><button className="filled-btn onboard-next" onClick={()=>step<2?setStep(step+1):setOnboarded(true)}>{step<2?'다음':'시작하기'}<ArrowRight size={18}/></button></div>}
 return <div className="app-shell">
 {!onboarded&&<Onboarding/>}
 <div className="app-scroll" ref={mainScroll}>
 {tab==='home'&&<>
  <PageHeader title="입찰공고 알리미" center actions={<button className="icon-button" aria-label="알림" onClick={()=>go('alerts')}><Bell size={20}/></button>}/>
  <div className="app-page home-page">
   <button type="button" className="home-search prominent" onClick={()=>go('search')}><Search size={17}/><span>공고명·키워드로 검색</span><ChevronRight size={16}/></button>
   {(interestCats.length>0||interestRegion!=='전국')&&<><SectionHeading title="오늘의 추천 공고" link="모두 보기" action={()=>go('search')}/>
   {requestStarted&&results.length>0?<div className="home-list">{results.slice(0,2).map((b,i)=><BidCard key={keyOf(b)+i} bid={b} onOpen={openDetail} saved={isSaved(b)} onSave={toggleSave}/>)}</div>:<div className="home-empty"><Sparkles size={20}/><p>{searchError?'지금은 보여드릴 공고가 없어요':'관심 업종·지역을 고르면 홈에서 나에게 맞는 공고를 먼저 보여드려요.'}</p><button onClick={()=>go('interest_categories')}>관심 업종 설정하기 <ChevronRight size={14}/></button></div>}</>}
   <SectionHeading title="업종으로 찾기"/>
   <p className="section-sub">내 업종을 누르면 관련 공고만 모아봐요</p>
   <div className="category-grid">{CATEGORIES.map(({id,text,Icon})=><button className="category-tile" key={id} onClick={()=>selectCategory(id)}><span className={'tile-icon '+id}><Icon size={20} strokeWidth={1.9}/></span><span>{text}</span></button>)}</div>
   <SectionHeading title="실제 수집된 최신 입찰공고" link="모두 보기" action={()=>runSearch({keyword:'',category:'',region:'전국'})}/>
   {homeLatest.length?<div className="home-list">{homeLatest.slice(0,3).map((b,i)=><BidCard key={keyOf(b)+i} bid={b} onOpen={openDetail} saved={isSaved(b)} onSave={toggleSave}/>)}</div>:<div className="home-empty compact"><Search size={20}/><p>현재 수집된 공고를 확인하고 있습니다.</p></div>}
   <SectionHeading title="지역으로 찾기" link="전체" action={()=>setPopup('region-home')}/><p className="section-sub">내 지역 공고를 한눈에</p>
   <div className="region-row">{REGIONS.slice(0,7).map(x=><button className="region-mini" onClick={()=>selectRegion(x)} key={x}><MapPin size={12}/>{x}</button>)}</div>
   <SectionHeading title="인기 검색어"/>
   <div className="plain-subtle">인기 검색어 순위는 아직 집계되지 않았습니다.</div>
   <SectionHeading title="마감 임박" link="모두 보기" action={()=>runSearch({deadlineSoon:true})}/>
   <div className="home-empty compact"><Clock size={22}/><p>곧 마감돼요. 서두르세요!<br/>실제 공고를 불러오지 못했습니다.</p></div>
   <div className="source-line">자료: 나라장터 공식 웹사이트 자체 수집 · 공고일과 마감일 등 미확인 항목은 별도 검증이 필요합니다.</div>
  </div>
 </>}
 {tab==='search'&&<>
  <PageHeader title="검색" actions={<button className="icon-button" onClick={openFilter} aria-label="필터"><SlidersHorizontal size={21}/></button>}/>
  <div className="app-page search-page">
   <form className="search-box" onSubmit={e=>{e.preventDefault();runSearch()}}><Search size={17}/><input aria-label="검색어" placeholder="공고명·키워드 (예: 청소, 급식)" value={query.keyword} onChange={e=>setQuery({...query,keyword:e.target.value})} ref={inputRef}/>{query.keyword&&<button type="button" className="clear-input" aria-label="지우기" onClick={()=>setQuery({...query,keyword:''})}><X size={15}/></button>}<button type="submit" className="search-submit">검색</button></form>
   <div className="sort-strip">{SORTS.map(x=><Chip key={x.id} active={query.sort===x.id} onClick={()=>switchSort(x.id)}>{x.text}</Chip>)}</div>
   <div className="quick-filters"><Chip active={query.region!=='전국'} onClick={()=>{setFilter(query);setPopup('regions')}}><MapPin size={13}/>{query.region||'전국'}</Chip><Chip active={query.deadlineSoon} onClick={()=>runSearch({deadlineSoon:!query.deadlineSoon})}>마감임박만</Chip><Chip active={query.includeClosed} onClick={()=>runSearch({includeClosed:!query.includeClosed})}>마감 포함</Chip><button type="button" className="filter-trigger" onClick={openFilter}><SlidersHorizontal size={14}/> 필터</button></div>
   {requestStarted?<div className="search-results-header"><span>{loading?'공고를 불러오는 중…':searchError?'검색':'검색 결과'}</span><b>{loading?'':searchError?'':countText}</b></div>:<div className="search-intro"><SectionHeading title="최근 검색어" link={recent.length?'모두 삭제':null} action={()=>setPopup('clear-recent')}/>{recent.length?<div className="recent-list">{recent.slice(0,10).map(x=><span key={x}><button onClick={()=>runSearch({keyword:x})}><Clock size={13}/>{x}</button><button title="삭제" onClick={()=>setRecent(recent.filter(v=>v!==x))}><X size={14}/></button></span>)}</div>:<p className="hint-copy">최근 검색어가 없어요</p>}<SectionHeading title="인기 검색어"/><p className="hint-copy">인기 검색어는 현재 집계되지 않았습니다.</p></div>}
   {requestStarted&&!loading&&!searchError&&resultsMeta?.filterNotes?.length>0&&<div className="inline-notice"><Info size={15}/><div>{(query.region!=='전국'||query.category||query.taskType||query.deadlineSoon)?resultsMeta.filterNotes.join(' '):'나라장터 공식 사이트에서 수집한 공고를 조회합니다. 공고별 상세 정보는 원문이 최종 기준입니다.'}</div></div>}
   {requestStarted&&loading&&!results.length&&<div className="loading-message"><RefreshCw className="spin" size={21}/>공고를 불러오는 중…</div>}
   {requestStarted&&searchError&&!loading&&<div className="error-panel"><AlertCircle size={25}/><h3>공고를 불러오지 못했어요</h3><p>{searchError}</p><button className="outline-btn" onClick={()=>load(query)}>다시 시도</button><small>실제 공고가 확인되지 않아 임의 데이터를 표시하지 않습니다.</small></div>}
   {requestStarted&&!searchError&&results.length===0&&!loading&&<EmptyState Icon={Search} title="검색 결과가 없어요" body="키워드나 지역·업무구분 필터를 바꿔서 다시 찾아보세요."/>}
   {results.length>0&&<div className="cards-list">{results.map((b,i)=><BidCard key={keyOf(b)+i} bid={b} onOpen={openDetail} saved={isSaved(b)} onSave={toggleSave}/>)}{resultsMeta?.hasMore&&<button className="load-more" onClick={loadNext} disabled={loading}>{loading?'불러오는 중…':'더 불러오기'} <ChevronDown size={15}/></button>}</div>}
   {!requestStarted&&<div className="search-empty"><Search size={26}/><h3>원하는 공고를 검색해 보세요</h3><p>공고명이나 키워드(예: 청소, 급식, 유지보수)로 찾을 수 있어요.<br/>위 필터 버튼으로 지역·업무구분도 좁힐 수 있어요.</p></div>}
  </div>
 </>}
 {tab==='saved'&&<>
  <PageHeader title="저장한 공고" actions={saved.length?<button className="text-action" onClick={()=>setPopup('clear-saved')}>모두 삭제</button>:null}/>
  <div className="app-page saved-page">
   {saved.length?<div className="cards-list">{saved.map((b,i)=><BidCard key={keyOf(b)+i} bid={b} onOpen={openDetail} saved={true} onSave={toggleSave}/>)}</div>:<EmptyState Icon={Bookmark} title="저장한 공고가 없어요" body="마음에 드는 공고의 책갈피(☆)를 눌러 저장하면 여기에서 모아볼 수 있어요." action={()=>go('search')} actionText="공고 검색하기"/>}
   <div className="source-line">저장한 공고는 이 기기에 보관돼요. 공고가 마감되거나 내려가도 저장 당시 내용을 다시 볼 수 있어요.</div>
  </div>
 </>}
 {tab==='alerts'&&<>
  <PageHeader title="공고 알림" actions={<button className="icon-button" onClick={()=>{setPreviewNotice('');setPopup('add-alert')}} aria-label="알림 조건 추가"><Plus size={25}/></button>}/>
  <div className="app-page alerts-page">
   <div className="alerts-intro"><BellRing size={22}/><div><b>맞춤 공고를 놓치지 마세요</b><p>관심 조건을 등록해 두면, 조건에 맞는 새 공고가 올라올 때 알림으로 알려드려요.</p></div></div>
   <InlineNotice tone="warn">웹앱 복제본의 서버 푸시 기능은 아직 연결되지 않았습니다. 현재 조건은 이 브라우저에만 보관됩니다.</InlineNotice>
   <SectionHeading title="내 알림 조건" link="추가" action={()=>{setPreviewNotice('');setPopup('add-alert')}}/>
   {alertRules.length?<div className="rules-list">{alertRules.map(a=><div className="rule-card" key={a.id}><div className="rule-title"><span><Bell size={17}/>{a.label}</span><button onClick={()=>{setPreviewNotice(String(a.id));setPopup('delete-alert')}} aria-label="알림 삭제"><Trash2 size={17}/></button></div><p>{[a.keyword,a.category?categoryName(a.category):'',a.region!=='전국'?a.region:'',typeLabel(a.taskType)].filter(Boolean).join(' · ')}</p><span className="local-pill">이 기기에만 저장됨 · 실제 푸시 미연결</span></div>)}</div>:<EmptyState Icon={Bell} title="등록한 알림 조건이 없어요" body="오른쪽 위 + 를 눌러 관심 조건을 추가하면 맞춤 공고가 올라올 때 알려드려요." action={()=>setPopup('add-alert')} actionText="알림 조건 추가"/>}
  </div>
 </>}
 {tab==='settings'&&<>
  <PageHeader title="설정"/>
  <div className="app-page settings-page">
   <SectionHeading title="관심 설정"/>
   <div className="settings-list"><button onClick={()=>go('interest_categories')}><span className="setting-icon"><LayoutGrid size={18}/></span><span className="setting-main">관심 업종<small>{interestCats.length?interestCats.map(categoryName).join(', '):'미설정'}</small></span><ChevronRight size={18}/></button><button onClick={()=>setPopup('interest-region')}><span className="setting-icon"><MapPin size={18}/></span><span className="setting-main">관심 지역<small>{interestRegion||'전국'}</small></span><ChevronRight size={18}/></button></div>
   <SectionHeading title="데이터 보관"/>
   <div className="settings-list"><button onClick={()=>setPopup('clear-recent')}><span className="setting-icon"><Clock size={18}/></span><span className="setting-main">최근 검색어 삭제<small>이 기기에 저장된 검색 기록</small></span><ChevronRight size={18}/></button><button onClick={()=>setPopup('clear-saved')}><span className="setting-icon"><Bookmark size={18}/></span><span className="setting-main">저장한 공고 모두 삭제<small>저장한 공고 {saved.length}건</small></span><ChevronRight size={18}/></button></div>
   <SectionHeading title="정보"/>
   <div className="settings-list"><a href="https://www.pickersoft.com/privacy_bidpicker.html" target="_blank" rel="noopener noreferrer"><span className="setting-icon"><ShieldCheck size={18}/></span><span className="setting-main">개인정보처리방침</span><ExternalLink size={17}/></a><a href="https://www.apple.com/legal/internet-services/itunes/dev/stdeula/" target="_blank" rel="noopener noreferrer"><span className="setting-icon"><FileText size={18}/></span><span className="setting-main">이용약관</span><ExternalLink size={17}/></a><div className="settings-static"><span className="setting-icon"><Info size={18}/></span><span className="setting-main">데이터 출처<small>조달청 나라장터(공공데이터포털)</small></span></div><div className="settings-static"><span className="setting-icon"><Info size={18}/></span><span className="setting-main">버전<small>1.0.1 원본 UI 참고 · 웹 복제본</small></span></div></div>
   <div className="source-line">저장한 공고와 검색 기록은 이 기기에만 보관돼요.</div>
  </div>
 </>}
 {tab==='interest_categories'&&<>
  <PageHeader title="관심 업종" onBack={()=>go('settings')} actions={<button className="text-action" onClick={()=>{setInterestCats(categoriesTemp);go('settings')}}>저장</button>}/>
  <div className="app-page categories-page"><h2>관심 업종을 설정해 보세요</h2><p>여러 업종을 함께 고를 수 있어요. 고른 업종의 키워드로 공고를 추천해 드려요.</p>
  <div className="categories-checks">{CATEGORIES.map(({id,text,Icon})=><button key={id} onClick={()=>setCategoriesTemp(prev=>prev.includes(id)?prev.filter(x=>x!==id):[...prev,id])} className={categoriesTemp.includes(id)?'on':''}><span className="setting-icon"><Icon size={19}/></span><span>{text}</span><span className="check-square">{categoriesTemp.includes(id)&&<Check size={15} strokeWidth={3}/>}</span></button>)}</div>
  <button className="filled-btn full" onClick={()=>{setInterestCats(categoriesTemp);go('settings')}}>적용</button></div>
 </>}
 {tab==='detail'&&<>
  <PageHeader title="공고 상세" onBack={back} actions={<><button className="icon-button" aria-label="저장" onClick={()=>actualDetail&&toggleSave(actualDetail)}><Bookmark size={19} fill={actualDetail&&isSaved(actualDetail)?'#0883a1':'none'}/></button><button className="icon-button" aria-label="공유" onClick={()=>actualDetail&&share(actualDetail)}><Share2 size={19}/></button></>}/>
  {actualDetail?<div className="app-page detail-page">
   <div className="detail-summary"><div className="bid-badges"><span className="kind-label">{typeLabel(actualDetail.taskType)}</span><StatusChip bid={actualDetail}/></div><h2>{actualDetail.title}</h2><div className="detail-sub">{actualDetail.bidNo||'공고번호 미확인'}</div></div>
   {actualDetail.summaryText&&<div className="overview"><b>한눈에 보기</b><p>{actualDetail.summaryText}</p></div>}
   <div className="detail-info">{[
    {Icon:Building2,name:'공고기관',value:actualDetail.agencyName||'미확인'},
    {Icon:Building2,name:'수요기관(실제 요청 기관)',value:actualDetail.demandAgencyName||'미확인'},
    {Icon:MapPin,name:'지역',value:actualDetail.region||'미확인'},
    {Icon:FileText,name:'공고종류',value:actualDetail.noticeKindName||'미확인'},
    {Icon:CalendarDays,name:'공고일',value:actualDetail.postedAt||'미확인'},
    {Icon:Clock,name:'마감일',value:actualDetail.deadlineAt||'미확인'},
    {Icon:CalendarDays,name:'개찰일',value:actualDetail.openingAt||'미확인'},
    {Icon:FileText,name:'계약방식',value:actualDetail.contractMethodName||'미확인'},
    {Icon:FileText,name:'입찰방식',value:actualDetail.bidMethodName||'미확인'},
    {Icon:FileText,name:'추정가격',value:prettyPrice(actualDetail.budgetAmount)}
   ].map(({Icon,name,value})=><div className="info-row" key={name}><Icon size={16}/><div><span>{name}</span><b>{value}</b></div></div>)}</div>
   {actualDetail.matchedKeywords?.length>0&&<div className="overview"><b>매칭된 키워드</b><p>아래 키워드가 공고에 포함돼 추천됐어요.</p><div className="keyword-strip">{actualDetail.matchedKeywords.map(w=><span key={w}>{w}</span>)}</div></div>}
   <InlineNotice>이 정보는 조달청 나라장터(공공데이터포털)에서 가져온 요약입니다. 참여 자격·서류·일정 등 정확한 내용은 반드시 원문 공고를 확인하세요. 공고 원문이 최종 기준입니다.</InlineNotice>
   {isSafeOriginalUrl(actualDetail.originalUrl)?<a className="detail-open" href={actualDetail.originalUrl} target="_blank" rel="noopener noreferrer">나라장터 원문 공고 보기 <ExternalLink size={18}/></a>:<button className="detail-open disabled" disabled>나라장터 원문 공고 보기 · 주소 미확인</button>}
  </div>:<EmptyState Icon={FileText} title="상세 정보를 불러오지 못했어요" body="검색 결과로 돌아가서 공고를 다시 선택해 주세요." action={()=>go('search')} actionText="검색으로 이동"/>}
 </>}
 </div>
 {!isSub&&<BottomNav tab={tab} onNavigate={go} savedCount={saved.length}/>}
 {popup==='filters'&&<Popup title="필터" onClose={()=>setPopup('')} footer={<><button className="outline-btn" onClick={clearFilter}>초기화</button><button className="filled-btn" onClick={applyFilters}>적용</button></>}>
  <div className="filter-section"><h3>업종</h3><div className="chip-flow"><Chip active={!filter.category} onClick={()=>setFilter({...filter,category:''})}>전체</Chip>{CATEGORIES.map(x=><Chip key={x.id} active={filter.category===x.id} onClick={()=>setFilter({...filter,category:x.id})}>{x.text}</Chip>)}</div></div>
  <div className="filter-section"><h3>지역</h3><div className="chip-flow">{REGIONS.map(r=><Chip key={r} active={filter.region===r} onClick={()=>setFilter({...filter,region:r})}>{r}</Chip>)}</div></div>
  <div className="filter-section"><h3>업무구분</h3><div className="chip-flow">{TYPES.map(t=><Chip key={t.id} active={filter.taskType===t.id} onClick={()=>setFilter({...filter,taskType:t.id})}>{t.text}</Chip>)}</div></div>
  <div className="filter-section"><h3>마감 조건</h3><label className="switch-row"><span>마감 임박만 보기</span><input type="checkbox" checked={filter.deadlineSoon} onChange={e=>setFilter({...filter,deadlineSoon:e.target.checked})}/></label><label className="switch-row"><span>마감된 공고도 포함</span><input type="checkbox" checked={filter.includeClosed} onChange={e=>setFilter({...filter,includeClosed:e.target.checked})}/></label></div>
 </Popup>}
 {(popup==='regions'||popup==='region-home'||popup==='interest-region')&&<Popup title="지역" onClose={()=>setPopup('')} footer={<button className="filled-btn full" onClick={()=>setPopup('')}>닫기</button>}><p className="popup-helper">지역은 현재 발주기관명 기준으로 검색합니다. 실제 입찰 참가 지역 제한과는 다릅니다.</p><div className="chip-flow">{REGIONS.map(r=><Chip key={r} active={popup==='interest-region'?interestRegion===r:query.region===r} onClick={()=>{if(popup==='interest-region'){setInterestRegion(r);setPopup('')}else selectRegion(r)}}>{r}</Chip>)}</div></Popup>}
 {popup==='clear-saved'&&<Popup title="저장한 공고를 모두 지울까요?" onClose={()=>setPopup('')} small footer={<><button className="outline-btn" onClick={()=>setPopup('')}>취소</button><button className="danger-btn" onClick={()=>{setSaved([]);setPopup('')}}>삭제</button></>}><p className="popup-helper">이 작업은 되돌릴 수 없어요.</p></Popup>}
 {popup==='clear-recent'&&<Popup title="최근 검색어를 모두 지울까요?" onClose={()=>setPopup('')} small footer={<><button className="outline-btn" onClick={()=>setPopup('')}>취소</button><button className="danger-btn" onClick={()=>{setRecent([]);setPopup('')}}>삭제</button></>}/>}
 {popup==='delete-alert'&&<Popup title="알림 조건 삭제" onClose={()=>setPopup('')} small footer={<><button className="outline-btn" onClick={()=>setPopup('')}>취소</button><button className="danger-btn" onClick={()=>{setAlertRules(v=>v.filter(a=>String(a.id)!==previewNotice));setPopup('');setPreviewNotice('')}}>삭제</button></>}><p className="popup-helper">선택한 맞춤 조건을 삭제하시겠습니까?</p></Popup>}
 {popup==='add-alert'&&<Popup title="알림 조건 추가" onClose={()=>setPopup('')} footer={<><button className="outline-btn" onClick={()=>{setPreviewNotice('지금은 미리보기를 불러올 수 없어요. 조건은 이 기기에만 저장할 수 있어요.')}}>미리보기</button><button className="filled-btn" onClick={saveRule}>저장</button></>}>
   <p className="popup-helper">조건에 맞는 새 공고가 올라오면 알려드려요.</p>
   <label className="text-field">조건 이름<input placeholder="맞춤 조건" value={alertsForm.label} onChange={e=>setAlertsForm({...alertsForm,label:e.target.value})}/></label>
   <label className="text-field">키워드<input placeholder="공고명·키워드 (예: 청소, 급식)" value={alertsForm.keyword} onChange={e=>setAlertsForm({...alertsForm,keyword:e.target.value})}/><span>키워드는 비워둬도 돼요. 업종·지역·업무구분만으로도 조건을 만들 수 있어요.</span></label>
   <div className="filter-section"><h3>업종</h3><div className="chip-flow"><Chip active={!alertsForm.category} onClick={()=>setAlertsForm({...alertsForm,category:''})}>전체</Chip>{CATEGORIES.map(x=><Chip key={x.id} active={alertsForm.category===x.id} onClick={()=>setAlertsForm({...alertsForm,category:x.id})}>{x.text}</Chip>)}</div></div>
   <div className="filter-section"><h3>지역</h3><div className="chip-flow">{REGIONS.map(r=><Chip key={r} active={alertsForm.region===r} onClick={()=>setAlertsForm({...alertsForm,region:r})}>{r}</Chip>)}</div></div>
   <div className="filter-section"><h3>업무구분</h3><div className="chip-flow">{TYPES.map(t=><Chip key={t.id} active={alertsForm.taskType===t.id} onClick={()=>setAlertsForm({...alertsForm,taskType:t.id})}>{t.text}</Chip>)}</div></div>
   {previewNotice&&<InlineNotice tone="warn">{previewNotice}</InlineNotice>}
 </Popup>}
 </div>;
}
export default App;
