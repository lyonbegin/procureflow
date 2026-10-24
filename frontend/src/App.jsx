import {
  useCallback, useEffect, useMemo, useRef, useState,
} from 'react';
import {
  ReactFlow, ReactFlowProvider, Background, Controls,
  MiniMap, Handle, Position, MarkerType, useReactFlow,
} from '@xyflow/react';
import {
  Activity, ArrowLeft, ArrowRight, BookOpen, Check, CheckCheck,
  CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, CircleHelp,
  Clock3, Database, Download, ExternalLink, FileSearch, FileText,
  GitBranch, History, Layers, LayoutDashboard, ListFilter, LoaderCircle,
  LockKeyhole, Menu, MoreHorizontal, Network, Play, Radar, RefreshCw,
  Search, ShieldCheck, SlidersHorizontal, TerminalSquare, X, XCircle,
  AlertCircle, Calculator, ClipboardCheck, HardDrive, Building2,
  Zap, ZoomIn, ListChecks, Info, PanelRightClose,
} from 'lucide-react';
import { api, SELECTED_BID } from './api.js';
import {
  GROUPS, GROUP_BY_ID, TOTAL_FEATURES,
  featureGroup, overviewGraph, detailGraph,
  graphCounts, groupCounts, groupState, parametersFromContract,
} from './workflow.js';

const LABELS = {
  verified: '검증 완료', partial: '부분 확보', missing: '증빙 부족',
  blocked: '진행 차단', error: '오류', unavailable: '미확인',
  queued: '대기 중', running: '실행 중', completed: '실행 종료',
  completed_partial: '일부 처리', failed: '실패', cancelled: '취소됨',
};
const ICONS = {
  radar: Radar, 'file-search': FileSearch, history: History,
  chart: Activity, shield: ShieldCheck, calculator: Calculator,
  check: CheckCheck,
};
const END_STATES = new Set(['completed', 'completed_partial', 'failed', 'cancelled']);
const STATUS_DOT = { verified: '#0d9a70', partial: '#d19428', missing: '#a5afbf',
  blocked: '#d19428', error: '#d44c63', unavailable: '#bcc6d5' };

function formatDate(value) {
  if (!value) return '미확인';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) :
    d.toLocaleString('ko-KR', { hour12: false, dateStyle: 'short', timeStyle: 'short' });
}
function formatJson(value) {
  if (value === undefined || value === null) return '반환된 데이터가 없습니다.';
  return JSON.stringify(value, null, 2);
}
function Status({ state, compact = false }) {
  const status = state || 'unavailable';
  return <span className={`status-badge ${status} ${compact ? 'compact' : ''}`}>
    <span className="status-dot" />{LABELS[status] || status}
  </span>;
}
function IconGroup({ group, size = 17 }) {
  const Comp = ICONS[group.icon] || Layers;
  return <Comp size={size} strokeWidth={1.9} aria-hidden="true" />;
}
function Ports() {
  return <>
    <Handle id="left" type="target" position={Position.Left} isConnectable={false} className="port"/>
    <Handle id="right" type="source" position={Position.Right} isConnectable={false} className="port"/>
    <Handle id="top" type="target" position={Position.Top} isConnectable={false} className="port"/>
    <Handle id="bottom" type="source" position={Position.Bottom} isConnectable={false} className="port"/>
    <Handle id="left-source" type="source" position={Position.Left} isConnectable={false} className="port"/>
    <Handle id="right-target" type="target" position={Position.Right} isConnectable={false} className="port"/>
  </>;
}
function TenderNode({ data }) {
  return <div className="flow-node tender-node">
    <Ports />
    <div className="node-eyebrow"><span className="node-icon violet"><Building2 size={18}/></span>
      <span>START · 발주정보</span></div>
    <strong title={data.title}>{data.title}</strong>
    <span className="node-subtitle">{data.bidNo || '발주번호 미확인'}</span>
    <span className="source-pip"><span className="live-dot"/>선택 공고 1건에서 시작</span>
  </div>;
}
function GroupNode({ data }) {
  const Icon = ICONS[data.icon] || Layers;
  const count = data.counts || {};
  const percent = count.total ? count.verified / count.total * 100 : 0;
  return <div className={`flow-node group-node state-${data.status || 'missing'}`}>
    <Ports />
    <div className="group-heading">
      <span className="node-icon teal"><Icon size={18}/></span>
      <span className="group-title">{data.title}</span>
      <ChevronRight size={17} className="muted-icon"/>
    </div>
    <p>{data.subtitle}</p>
    <div className="group-foot"><Status state={data.status} compact />
      <span>{count.loaded ? count.verified + ' / ' + count.total : '— / ' + count.total}</span>
    </div>
    <div className="mini-progress"><span style={{ width: percent + '%' }}/></div>
  </div>;
}
function FeatureNode({ data }) {
  return <div className={`flow-node function-node state-${data.status || 'missing'} ${data.selected ? 'chosen' : ''}`}>
    <Ports />
    <div className="function-row"><span className="function-number">#{String(data.number).padStart(3, '0')}</span>
      <Status state={data.status} compact /></div>
    <strong title={data.title}>{data.title}</strong>
    <div className="function-foot"><span>원본·결과 확인</span>
      <ArrowRight size={15}/></div>
  </div>;
}
function FinishNode({ data }) {
  return <div className="flow-node finish-node">
    <Ports/>
    <div className="node-eyebrow"><span className="node-icon slate"><LockKeyhole size={18}/></span>
      <span>FINAL CHECK</span></div>
    <strong>{data.label}</strong>
    <span className="node-subtitle">{data.subtitle}</span>
    <span className="not-submitted">자동 입찰 제출 없음</span>
  </div>;
}
const NODE_TYPES = { tender: TenderNode, group: GroupNode, feature: FeatureNode, finish: FinishNode };

function Canvas({ catalog, context, view, selectedNumber, onNodeClick }) {
  const instance = useReactFlow();
  const graph = useMemo(() => view === 'overview'
    ? overviewGraph(catalog, context || {})
    : detailGraph(catalog, view, selectedNumber, context || {}),
    [catalog, context, view, selectedNumber]);
  const edges = useMemo(() => graph.edges.map((e) => ({
    ...e, markerEnd: { type: MarkerType.ArrowClosed, color: '#9fb1c4', width: 14, height: 14 },
  })), [graph.edges]);
  useEffect(() => {
    const timer = setTimeout(() => instance.fitView({ padding: 0.19, duration: 350, maxZoom: 1.15 }), 90);
    return () => clearTimeout(timer);
  }, [instance, view, catalog.length]);
  return <ReactFlow
    nodes={graph.nodes} edges={edges} nodeTypes={NODE_TYPES}
    onNodeClick={(_, node) => onNodeClick(node.id)}
    fitView fitViewOptions={{ padding: 0.16, maxZoom: 1.15 }}
    minZoom={0.21} maxZoom={1.8}
    nodesDraggable={false} nodesConnectable={false}
    elementsSelectable selectionOnDrag={false}
    panOnDrag zoomOnScroll zoomOnPinch
    proOptions={{ hideAttribution: false }}
  >
    <Background color="#d8e2ef" gap={22} size={1.05}/>
    <MiniMap className="mini-map" pannable zoomable nodeColor={(node) =>
      node.type === 'tender' ? '#a993d0' :
      node.type === 'finish' ? '#95a3b7' :
      STATUS_DOT[node.data?.status] || '#5fa9b3'} />
    <Controls className="flow-controls" showInteractive={false}/>
  </ReactFlow>;
}

function SideMenu({ catalog, view, onGroup, query, setQuery, onFeature, mobileOpen, setMobileOpen }) {
  const filtered = query.trim()
    ? catalog.filter((f) => (String(f.number) + ' ' + f.name).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).slice(0, 25)
    : [];
  return <aside className={`side-rail ${mobileOpen ? 'mobile-open' : ''}`}>
    <div className="brand">
      <div className="brand-mark"><Network size={20} strokeWidth={2.4}/></div>
      <div className="brand-copy"><strong>ProcureFlow</strong><span>PROCUREMENT STUDIO</span></div>
      <button className="mobile-close icon-button" onClick={() => setMobileOpen(false)} aria-label="메뉴 닫기"><X size={18}/></button>
    </div>
    <div className="sidebar-scroll">
      <div className="side-section-label">WORKSPACE</div>
      <button className={`side-tab ${view === 'overview' ? 'active' : ''}`}
        onClick={() => { onGroup('overview'); setMobileOpen(false); }}>
        <LayoutDashboard size={18}/><span>전체 워크플로</span><span className="nav-quiet">7</span>
      </button>
      <div className="side-section-label sections-label">업무별 워크플로 <span>104 FUNCTIONS</span></div>
      <div className="workflow-menu">
        {GROUPS.map((group) => {
          const counts = groupCounts(catalog, group);
          return <button key={group.key} className={`workflow-menu-item ${view === group.key ? 'active' : ''}`}
            onClick={() => { onGroup(group.key); setMobileOpen(false); }}>
            <span className="group-menu-icon"><IconGroup group={group}/></span>
            <span className="menu-title"><strong>{group.title}</strong>
              <small>{group.range[0]}–{group.range[1]}번 기능</small></span>
            <span className="menu-count">{counts.loaded ? counts.verified : '—'}/{counts.total}</span>
          </button>;
        })}
      </div>
      <div className="side-search-label">기능 바로 찾기</div>
      <div className="side-search"><Search size={15}/><input
        type="search" value={query} onChange={(event) => setQuery(event.target.value)}
        placeholder="번호 또는 기능명 검색…" aria-label="기능 검색" /></div>
      {query.trim() && <div className="search-results">
        {filtered.length ? filtered.map((f) =>
          <button key={f.number} onClick={() => { onFeature(f.number); setMobileOpen(false); }}>
            <span>#{String(f.number).padStart(3, '0')}</span><strong>{f.name}</strong>
          </button>) : <div className="search-empty">검색된 기능이 없습니다.</div>}
      </div>}
      <div className="side-section-label other-label">기존 운영 화면</div>
      <nav className="legacy-nav" aria-label="기존 운영 도구">
        <a href="/legacy/workbench"><BookOpen size={16}/>발주 · 입찰 목록 <ExternalLink size={12}/></a>
        <a href="/bids"><Database size={16}/>개찰 · 낙찰 데이터 <ExternalLink size={12}/></a>
        <a href="/operations"><HardDrive size={16}/>수집기 · 운영 관리 <ExternalLink size={12}/></a>
        <a href="/agents"><Activity size={16}/>에이전트 운영 <ExternalLink size={12}/></a>
        <a href="/prepare"><FileText size={16}/>가격 · 제안서 검토 <ExternalLink size={12}/></a>
        <a href="/docs"><BookOpen size={16}/>API 문서 <ExternalLink size={12}/></a>
      </nav>
    </div>
    <div className="sidebar-footer"><span className="privacy-mark"><ShieldCheck size={17}/></span>
      <div><strong>검증 기준 운영</strong><small>실제 투찰 · 서명 · 제출 없음</small></div></div>
  </aside>;
}

function NextStepBar({ plan, error, tokenReady, onInspect, onAdvance, busy, actionError }) {
  const next = plan?.recommended_next;
  if (!plan && !error) return <section className="next-step-bar loading-next">
    <LoaderCircle size={17} className="spinning"/><span>현재 원본 증빙을 기준으로 다음 처리 단계 계산 중…</span>
  </section>;
  if (!plan) return <section className="next-step-bar blocked-next">
    <AlertCircle size={17}/><div><strong>다음 실행 계획 조회 실패</strong><p>{error}</p></div>
  </section>;
  const actionable = next?.status === 'actionable' && plan.allowed_to_enqueue;
  const competing = !!plan.active_jobs?.length;
  const label = next?.status === 'actionable' ? '단일 작업 실행 가능'
    : next?.status === 'manual_input_required' ? '증빙 자료 입력 필요'
    : next?.status === 'manual_review_required' ? '최종 수동 검토'
    : '선행 원본 확인 필요';
  return <section className={`next-step-bar ${actionable ? 'ready-next' : 'blocked-next'}`}>
    <div className="next-step-icon">{actionable ? <GitBranch size={19}/> : <AlertCircle size={19}/>}</div>
    <div className="next-step-message">
      <div className="next-step-top"><strong>다음 작업 추천</strong>
        <span className="next-tag">{label}</span></div>
      <p>{next?.group && GROUP_BY_ID[next.group] ? GROUP_BY_ID[next.group].title + ' · ' : ''}
        {next?.feature_no ? '#' + String(next.feature_no).padStart(3, '0') + ' · ' : ''}
        {next?.reason || '계획 없음'}</p>
      {next?.required?.length > 0 && <small>부족한 원본/증빙: {next.required.join(', ')}</small>}
      {competing && <small>실행 중인 기능 작업 {plan.active_jobs.length}건 · 중복 작업은 생성하지 않습니다.</small>}
      {actionError && <small className="next-error" role="alert">{actionError}</small>}
    </div>
    {next?.feature_no && <div className="next-step-actions">
      <button className="button secondary" onClick={() => onInspect(next.feature_no)}>
        <SlidersHorizontal size={15}/>노드 열기</button>
      {actionable && <button className="button primary" disabled={busy || !tokenReady}
        title={tokenReady ? '현재 추천된 작업 1개만 실행' : '노드에서 관리자 토큰 입력 후 실행'}
        onClick={onAdvance}>{busy ? <LoaderCircle size={15} className="spinning"/> : <Play size={15}/>}
        다음 1단계 실행</button>}
    </div>}
  </section>;
}

function StatStrip({ catalog, isLoading }) {
  const stats = graphCounts(catalog);
  return <div className="stats-strip">
    <div className="metric"><span className="metric-icon blue"><Layers size={17}/></span>
      <div><strong>{isLoading && !catalog.length ? '—' : stats.total}</strong><small>전체 기능</small></div></div>
    <div className="metric"><span className="metric-icon green"><CheckCircle2 size={17}/></span>
      <div><strong>{stats.loaded ? stats.verified : '—'}</strong><small>원본 검증</small></div></div>
    <div className="metric"><span className="metric-icon yellow"><Clock3 size={17}/></span>
      <div><strong>{stats.loaded ? stats.partial : '—'}</strong><small>부분 확보</small></div></div>
    <div className="metric"><span className="metric-icon red"><AlertCircle size={17}/></span>
      <div><strong>{stats.loaded ? stats.missing : '—'}</strong><small>미확보 · 오류</small></div></div>
    <div className="metric detail-metric">
      <div className="progress-header"><span>전체 검증률</span><strong>{stats.loaded ? Math.floor(stats.verified / stats.total * 100) + '%' : '—'}</strong></div>
      <div className="metric-progress"><span style={{ width: (stats.verified / stats.total * 100) + '%' }}/></div>
    </div>
  </div>;
}

function NoticeData({ context }) {
  const attributes = [
    ['공고번호', context?.bid_no || SELECTED_BID],
    ['발주기관', context?.agency || '원본 확인 필요'],
    ['기관 코드', context?.agency_code || '미확보'],
    ['공고차수', context?.bid_ord || '000'],
    ['10자리 세부품명', context?.official_detail10?.join(', ') || '공식 원본 확인 필요'],
    ['입찰 마감일', context?.deadline || '미확보'],
  ];
  return <div className="notice-data-grid">
    {attributes.map(([name, value]) => <div key={name}><span>{name}</span><strong title={String(value)}>{value}</strong></div>)}
  </div>;
}

function GroupIntro({ catalog, view, onFeature }) {
  const group = GROUP_BY_ID[view];
  if (!group) return null;
  const count = groupCounts(catalog, group);
  const within = catalog.filter((f) => f.group === view);
  return <div className="inspector-body">
    <div className="inspect-empty-icon"><IconGroup group={group} size={28}/></div>
    <h3>{group.title}</h3>
    <p className="helper">{group.subtitle}. 아래 기능을 하나씩 선택하여 입력·출력과 현재 원본 증빙을 확인하고 실행할 수 있습니다.</p>
    <div className="group-status-block"><Status state={groupState(count)}/>
      <span>검증 완료 {count.loaded ? count.verified : '—'} / {count.total}</span></div>
    <div className="inspector-section-heading">포함된 기능</div>
    <div className="quick-feature-list">
      {within.map((f) => <button onClick={() => onFeature(f.number)} key={f.number}>
        <span className="quick-no">{String(f.number).padStart(3, '0')}</span>
        <span>{f.name}</span><span className={'tiny-dot ' + f.acceptance_state}/></button>)}
    </div>
  </div>;
}

function ReadOnlyInputs({ items }) {
  return <div className="autofacts">
    {(items || []).map((i) => <div className="autofact" key={i.name}>
      <div><span>{i.name}</span><small>{i.source === 'official_classification' ? '공식 분류' : '공고 자동 입력'}</small></div>
      <strong>{Array.isArray(i.value) ? (i.value.length ? i.value.join(', ') : '미확보') : (i.value ?? '미확보')}</strong>
    </div>)}
  </div>;
}
function ParametersEditor({ schema, params, onChange }) {
  const entries = Object.entries(schema || {});
  if (!entries.length) return <div className="no-extra">추가 입력값 없음. 모든 값은 선택된 발주정보에서 자동 연결됩니다.</div>;
  return <div className="param-list">{entries.map(([name, def]) => <label className="param-field" key={name}>
    <span>{name} <small>{def.type}</small></span>
    <input
      type={def.type === 'integer' ? 'number' : 'text'}
      min={def.minimum} max={def.maximum} maxLength={def.maxLength}
      value={params[name] ?? ''} placeholder={def.description || ''}
      onChange={(event) => onChange((prev) => ({
        ...prev,
        [name]: def.type === 'integer' ? (event.target.value === '' ? '' : Number(event.target.value)) : event.target.value,
      }))} />
    <small>{def.description || (def.minimum ? def.minimum + ' ~ ' + def.maximum : '')}</small>
  </label>)}</div>;
}

function Inspector({
  context, catalog, view, selectedNumber, detail, detailLoading, detailError,
  tab, setTab, params, setParams, token, setToken, onInspect, onRun,
  actionBusy, actionError, job, runs, runsLoading, onFeature, runHistory,
  collapse, setCollapse,
}) {
  if (collapse) return <button className="expand-inspector" onClick={() => setCollapse(false)}
    title="설정 패널 열기"><SlidersHorizontal size={17}/><span>설정</span></button>;
  const group = view === 'overview' ? null : GROUP_BY_ID[view];
  const selected = catalog.find((f) => f.number === selectedNumber);
  return <aside className="inspector" aria-label="기능별 설정과 결과">
    <div className="inspector-header">
      <div><span className="inspector-overline">INSPECTOR</span>
        <h2>{selected ? '기능 상세 설정' : group ? '업무 그룹' : '발주정보'}</h2></div>
      <button className="icon-button" onClick={() => setCollapse(true)} title="패널 접기"><PanelRightClose size={18}/></button>
    </div>
    {!selected ? group ? <GroupIntro catalog={catalog} view={view} onFeature={onFeature}/> :
      <div className="inspector-body">
        <div className="inspect-empty-icon"><Building2 size={27}/></div>
        <h3>발주정보에서 시작</h3>
        <p className="helper">모든 104개 기능이 선택 공고의 원본 데이터를 입력값으로 사용합니다. 그룹 또는 노드를 선택하여 세부 실행 결과를 확인하세요.</p>
        <NoticeData context={context}/>
        <div className="caution-note"><Info size={16}/>입찰공고 원본이 확인되지 않은 항목은 완료로 표시하지 않습니다.</div>
      </div> :
      <div className="inspect-content">
        <div className="selection-title">
          <span className="function-id">FUNCTION {String(selectedNumber).padStart(3, '0')}</span>
          <h3>{selected.name}</h3>
          <div className="selection-status"><Status state={detail?.acceptance_state || selected.acceptance_state}/>
            <span>{GROUP_BY_ID[selected.group]?.title}</span></div>
        </div>
        <div className="inspector-tabs" role="tablist">
          {['설정', '결과', '이력'].map((name, index) => <button key={name}
            role="tab" aria-selected={tab === index}
            className={tab === index ? 'active' : ''}
            onClick={() => { setTab(index); if (index === 2) runHistory(selectedNumber); }}>{name}</button>)}
        </div>
        {detailLoading && <div className="load-note"><LoaderCircle size={16} className="spinning"/>기능 원본과 입력 계약 조회 중…</div>}
        {detailError && <div className="error-note">{detailError}</div>}
        {tab === 0 && <div className="inspector-tab-content">
          <div className="inspector-section-heading">발주정보 자동 연결 <span className="locked-label"><LockKeyhole size={13}/>잠김</span></div>
          <ReadOnlyInputs items={detail?.input_contract?.auto_from_selected_notice || [
            { name: 'bid_no', value: context?.bid_no || SELECTED_BID, source: 'selected_notice' },
            { name: 'detail10', value: context?.official_detail10 || [], source: 'official_classification' },
          ]}/>
          <div className="inspector-section-heading">추가 파라미터</div>
          <ParametersEditor schema={detail?.input_contract?.parameters || selected.input_contract?.parameters}
            params={params} onChange={setParams}/>
          <div className="inspector-section-heading">완료에 필요한 증빙</div>
          <div className="evidence-list">
            {(detail?.input_contract?.required_verified_evidence || selected.input_contract?.required_verified_evidence || []).map((name) =>
              <div key={name} className={detail?.verified_evidence?.includes(name) ? 'satisfied' : ''}>
                {detail?.verified_evidence?.includes(name) ? <CheckCircle2 size={15}/> : <CircleHelp size={15}/>}
                <span>{name}</span></div>)}
          </div>
          <div className="auth-field">
            <label htmlFor="admin-token"><LockKeyhole size={15}/> 관리자 실행 토큰</label>
            <input id="admin-token" type="password" autoComplete="off"
              value={token} onChange={(e) => setToken(e.target.value)}
              placeholder="실행 시에만 필요 · 저장 안 함"/>
            <small>브라우저 상태에만 보관하고 서버의 파일·DB에 저장하지 않습니다.</small>
          </div>
          {actionError && <div className="error-note" role="alert">{actionError}</div>}
          <div className="inspector-actions">
            <button className="button secondary" disabled={detailLoading || actionBusy}
              onClick={onInspect}><RefreshCw size={16}/>현재 상태 재검사</button>
            <button className="button primary" disabled={!token.trim() || actionBusy || detailLoading}
              onClick={onRun}>{actionBusy ? <LoaderCircle size={16} className="spinning"/> : <Play size={16}/>}개별 실행</button>
          </div>
          <p className="small-disclaimer">실행 요청은 Railway Worker 작업 큐에 등록됩니다. 작업 완료와 원본 검증 완료는 다릅니다.</p>
        </div>}
        {tab === 1 && <div className="inspector-tab-content">
          <div className="inspector-section-heading">실제 기능 반환 데이터</div>
          <div className="result-source"><span>데이터 원천</span><strong>{detail?.observation?.source || '미확인'}</strong></div>
          <div className="result-source"><span>수집/관측 상태</span><strong>{detail?.observation?.status || '미확인'}</strong></div>
          <pre className="json-view">{formatJson(detail?.observation || (detailLoading ? { status: 'loading' } : null))}</pre>
          <div className="inspector-section-heading">검증 근거 및 부족 항목</div>
          <pre className="json-view compact-json">{formatJson({
            verified: detail?.verified_evidence || [],
            missing: detail?.missing_evidence || [],
            acceptance_state: detail?.acceptance_state || selected.acceptance_state,
          })}</pre>
        </div>}
        {tab === 2 && <div className="inspector-tab-content">
          <div className="inspector-section-heading">개별 실행 기록</div>
          {runsLoading && <div className="load-note"><LoaderCircle size={15} className="spinning"/>로그 조회 중…</div>}
          {!runsLoading && !runs.length && <div className="no-extra">실제 실행 기록이 없습니다.</div>}
          {runs.map((run) => <details className="run-entry" key={run.id}>
            <summary><span><strong>#{run.id}</strong> {formatDate(run.created_at)}</span><Status state={run.state} compact/></summary>
            <div className="run-entry-content">
              {run.error && <p className="error-note">{run.error}</p>}
              <pre className="json-view">{formatJson(run.result)}</pre>
            </div>
          </details>)}
          <button className="button ghost" onClick={() => runHistory(selectedNumber)}><RefreshCw size={14}/>이력 다시 읽기</button>
        </div>}
      </div>}
    <div className="inspector-bottom">
      <span className="safety-icon"><LockKeyhole size={14}/></span>
      <span>입찰참가 · 전자서명 · 실제 제출 차단</span>
    </div>
  </aside>;
}

function Console({ open, setOpen, job, jobError, onRefresh, selectedNumber }) {
  return <section className={`console-bar ${open ? 'open' : ''}`}>
    <button className="console-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
      <span><TerminalSquare size={17}/>실행 콘솔</span>
      <span className="console-right">
        {job ? <>기능 #{String(job.feature_no || selectedNumber || '').padStart(3, '0')} · {LABELS[job.state] || job.state}</> : '작업 대기'}
        {open ? <ChevronDown size={16}/> : <ChevronUpIcon/>}
      </span>
    </button>
    {open && <div className="console-body">
      {job ? <>
        <div className="console-meta"><span>JOB #{job.job_id}</span><Status state={job.state}/>
          <span>요청 기능: #{job.feature_no}</span></div>
        <pre>{formatJson({
          state: job.state, message: job.message || job.job_status,
          error: job.error || null, job_id: job.job_id, completed_at: job.finished_at || null,
          run_id: job.run_id || null,
          execution_result: job.execution_result || null,
        })}</pre>
        {END_STATES.has(job.state) && <button className="button ghost" onClick={onRefresh}>
          <RefreshCw size={14}/>최신 증빙 다시 확인</button>}
      </> : <div className="console-placeholder"><Activity size={16}/>노드를 선택한 뒤 개별 실행하면 작업 상태와 오류가 여기에 표시됩니다.</div>}
      {jobError && <div className="error-note">{jobError}</div>}
    </div>}
  </section>;
}
function ChevronUpIcon() { return <ChevronDown size={16} style={{ transform: 'rotate(180deg)' }}/>; }

function StudioApp() {
  const [catalog, setCatalog] = useState([]);
  const [context, setContext] = useState(null);
  const [catalogBusy, setCatalogBusy] = useState(true);
  const [catalogError, setCatalogError] = useState('');
  const [plan, setPlan] = useState(null);
  const [planError, setPlanError] = useState('');
  const [advanceBusy, setAdvanceBusy] = useState(false);
  const [advanceError, setAdvanceError] = useState('');
  const [lastRead, setLastRead] = useState(null);
  const [view, setView] = useState('overview');
  const [selectedNumber, setSelectedNumber] = useState(null);
  const [inspector, setInspector] = useState(null);
  const [inspectBusy, setInspectBusy] = useState(false);
  const [inspectError, setInspectError] = useState('');
  const [params, setParams] = useState({});
  const [tab, setTab] = useState(0);
  const [token, setToken] = useState('');
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [activeJob, setActiveJob] = useState(null);
  const [jobError, setJobError] = useState('');
  const [runs, setRuns] = useState([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [query, setQuery] = useState('');
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [collapsedInspector, setCollapsedInspector] = useState(false);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [reloadIndex, setReloadIndex] = useState(0);
  const inFlightRef = useRef(false);
  const currentSelectionRef = useRef(null);
  useEffect(() => { currentSelectionRef.current = selectedNumber; }, [selectedNumber]);

  const refresh = useCallback(async (quiet = false) => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    if (!quiet) setCatalogBusy(true);
    try {
      const data = await api.catalog();
      if (data.total !== 104 || !Array.isArray(data.features) || data.features.length !== 104) {
        throw new Error('서버의 104개 기능 목록이 완전하지 않습니다. 원본을 재확인하세요.');
      }
      setContext(data.context);
      setCatalog(data.features);
      setCatalogError('');
      setLastRead(new Date());
      try {
        const next = await api.plan();
        setPlan(next);
        setPlanError('');
      } catch (error) {
        setPlanError(error.message);
      }
    } catch (err) {
      setCatalogError(err.message);
    } finally {
      setCatalogBusy(false);
      inFlightRef.current = false;
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(() => refresh(true), 60000);
    return () => clearInterval(timer);
  }, [refresh]);

  const loadRuns = useCallback(async (number) => {
    if (!number) return;
    setRunsLoading(true);
    try {
      const response = await api.runs(number);
      if (currentSelectionRef.current === number) setRuns(response.runs || []);
    } catch (error) {
      if (currentSelectionRef.current === number) setInspectError(error.message);
    } finally { setRunsLoading(false); }
  }, []);

  const loadInspector = useCallback(async (number, retainTab = false) => {
    if (!number) return;
    setInspectBusy(true);
    setInspectError('');
    try {
      const data = await api.feature(number);
      if (currentSelectionRef.current !== number) return;
      setInspector(data);
      if (!retainTab) setParams(parametersFromContract(data.input_contract?.parameters));
    } catch (error) {
      if (currentSelectionRef.current === number) setInspectError(error.message);
    } finally { if (currentSelectionRef.current === number) setInspectBusy(false); }
  }, []);

  useEffect(() => {
    if (!selectedNumber) {
      setInspector(null); setRuns([]); setActionError('');
      return;
    }
    setInspector(null);
    loadInspector(selectedNumber);
    loadRuns(selectedNumber);
  }, [selectedNumber, loadInspector, loadRuns, reloadIndex]);

  const openFeature = useCallback((number) => {
    if (!featureGroup(number)) return;
    currentSelectionRef.current = number;
    setView(featureGroup(number));
    setSelectedNumber(number);
    setTab(0); setActionError(''); setCollapsedInspector(false);
  }, []);

  const openGroup = useCallback((key) => {
    setView(key);
    setSelectedNumber(null);
    currentSelectionRef.current = null;
    setTab(0);
    setCollapsedInspector(false);
  }, []);

  const onNodeClick = useCallback((id) => {
    if (id === 'tender') openGroup('overview');
    else if (id === 'finish') openGroup('operations');
    else if (id.startsWith('group:')) openGroup(id.slice(6));
    else if (id.startsWith('feature:')) openFeature(Number(id.slice(8)));
  }, [openFeature, openGroup]);

  const runHistory = useCallback((number) => loadRuns(number), [loadRuns]);

  const runOne = useCallback(async () => {
    if (!selectedNumber || !inspector) return;
    if (!token.trim()) { setActionError('작업 실행에는 관리자 토큰이 필요합니다.'); return; }
    setActionBusy(true); setActionError('');
    try {
      const spec = inspector.input_contract?.parameters || {};
      const safeParameters = {};
      for (const [name, value] of Object.entries(params)) {
        if (!(name in spec)) throw new Error('지원하지 않는 파라미터: ' + name);
        if (value === '' || value === null || value === undefined) continue;
        if (spec[name].type === 'integer' &&
           (!Number.isInteger(value) || value < spec[name].minimum || value > spec[name].maximum))
          throw new Error(name + ': 허용 범위 ' + spec[name].minimum + ' ~ ' + spec[name].maximum);
        safeParameters[name] = value;
      }
      const response = await api.run(selectedNumber, 'collect', safeParameters, token);
      setActiveJob({ job_id: response.job_id, feature_no: selectedNumber,
        state: response.job_status || 'queued', job_status: '작업 대기 등록됨' });
      setConsoleOpen(true);
    } catch (error) { setActionError(error.message); }
    finally { setActionBusy(false); }
  }, [selectedNumber, inspector, token, params]);

  const advanceOne = useCallback(async () => {
    const next = plan?.recommended_next;
    if (!next || !plan?.allowed_to_enqueue || !next.feature_no) return;
    if (!token.trim()) {
      openFeature(next.feature_no);
      setAdvanceError('관리자 토큰 입력 후 실행할 수 있습니다.');
      return;
    }
    setAdvanceBusy(true);
    setAdvanceError('');
    try {
      const queued = await api.advance(next.feature_no, token);
      setActiveJob({ job_id: queued.job_id, feature_no: queued.feature_no,
        state: queued.job_status || 'queued', job_status: '추천 작업 1개 대기 등록됨' });
      setConsoleOpen(true);
      setPlan((previous) => previous && {
        ...previous, allowed_to_enqueue: false,
        active_jobs: [{ id: queued.job_id, feature_no: String(queued.feature_no), state: 'queued' }],
      });
    } catch (error) {
      setAdvanceError(error.message);
      await refresh(true);
    } finally { setAdvanceBusy(false); }
  }, [plan, token, openFeature, refresh]);

  useEffect(() => {
    if (!activeJob?.job_id || END_STATES.has(activeJob.state)) return;
    let alive = true;
    const poll = async () => {
      try {
        const state = await api.job(activeJob.job_id, token);
        if (!alive) return;
        setActiveJob(state);
        setJobError('');
        if (END_STATES.has(state.state)) {
          refresh(true);
          if (currentSelectionRef.current) {
            loadInspector(currentSelectionRef.current, true);
            loadRuns(currentSelectionRef.current);
          }
        }
      } catch (err) { if (alive) setJobError(err.message); }
    };
    const timer = setInterval(poll, 3000);
    return () => { alive = false; clearInterval(timer); };
  }, [activeJob?.job_id, activeJob?.state, token, refresh, loadInspector, loadRuns]);

  const section = GROUP_BY_ID[view];
  const selectedFeature = catalog.find((x) => x.number === selectedNumber);
  return <div className="shell">
    {mobileMenu && <button className="mobile-overlay" aria-label="메뉴 닫기" onClick={() => setMobileMenu(false)} />}
    <SideMenu catalog={catalog} view={view} onGroup={openGroup} query={query}
      setQuery={setQuery} onFeature={openFeature} mobileOpen={mobileMenu} setMobileOpen={setMobileMenu}/>
    <div className="app-main">
      <header className="app-topbar">
        <div className="breadcrumbs">
          <button className="icon-button mobile-menu" onClick={() => setMobileMenu(true)} aria-label="메뉴"><Menu size={19}/></button>
          <span>워크스페이스</span><ChevronRight size={14}/>
          <strong>{view === 'overview' ? '전체 워크플로' : section?.title}</strong>
        </div>
        <div className="topbar-actions">
          <span className="topbar-latest"><span className="live-dot"/> DB 원본 기준 {lastRead ? formatDate(lastRead) : '조회 중'}</span>
          <button className="button light" onClick={() => refresh()} disabled={catalogBusy}>
            <RefreshCw size={15} className={catalogBusy ? 'spinning' : ''}/>새로고침</button>
          <a className="button light topbar-api" href="/docs" target="_blank" rel="noopener"><BookOpen size={15}/>API</a>
        </div>
      </header>
      <div className="workspace">
        <div className="page-lead">
          <div className="page-heading">
            <div className="eyebrow"><span className="eyebrow-line"/>PROCUREMENT WORKFLOW</div>
            <h1>{view === 'overview' ? '입찰 워크플로 운영' : section?.title}</h1>
            <p>{view === 'overview'
              ? '한 건의 발주정보를 기준으로 104개 기능을 연결하고, 원본 증빙과 작업 실행을 한곳에서 관리합니다.'
              : `${section.subtitle} · 기능 #${section.range[0]}–#${section.range[1]} · 노드를 선택해 결과를 확인하세요.`}</p>
          </div>
          <div className="case-chip" title={context?.title || ''}>
            <div className="chip-icon"><Building2 size={19}/></div>
            <div><small>선택한 발주정보</small><strong>{context?.title || '발주정보 불러오는 중…'}</strong>
              <span>{SELECTED_BID} · {context?.agency || '발주기관 확인 중'}</span></div>
            <span className="chip-status"><Status state={context?.original_notice_verified ? 'verified' : 'missing'} compact/></span>
          </div>
        </div>
        {catalogError && <div className="fetch-error" role="alert"><AlertCircle size={18}/>
          <div><strong>운영 DB 연결 또는 104개 기능 조회 실패</strong><p>{catalogError} · 저장된 결과를 임의로 표시하지 않습니다.</p></div>
          <button className="button light" onClick={() => refresh()}>재시도</button></div>}
        <NextStepBar plan={plan} error={planError} tokenReady={!!token.trim()}
          onInspect={openFeature} onAdvance={advanceOne} busy={advanceBusy}
          actionError={advanceError}/>
        <StatStrip catalog={catalog} isLoading={catalogBusy}/>
        <div className="work-area">
          <section className="canvas-column">
            <div className="canvas-toolbar">
              <div className="canvas-breadcrumbs">
                {view !== 'overview' && <button className="back-flow" onClick={() => openGroup('overview')}>
                  <ArrowLeft size={15}/>전체 흐름</button>}
                <span className="toolbar-title"><GitBranch size={16}/>
                  {view === 'overview' ? '전체 파이프라인' : section?.title + ' · 세부 기능'}</span>
                <span className="toolbar-count">{view === 'overview' ? '7개 그룹' : ((section?.range[1] || 0) - (section?.range[0] || 0) + 1) + '개 기능'}</span>
              </div>
              <span className="canvas-help"><Info size={15}/>노드를 클릭해 상세 확인</span>
            </div>
            <div className="flow-stage">
              {catalog.length ? <Canvas catalog={catalog} context={context}
                view={view} selectedNumber={selectedNumber} onNodeClick={onNodeClick}/> :
                <div className="graph-loading"><LoaderCircle size={25} className={catalogBusy ? 'spinning' : ''}/>
                  <strong>{catalogBusy ? '104개 기능의 실제 상태를 불러오는 중' : '발주정보를 조회하지 못했습니다'}</strong>
                  <p>실제 결과를 받기 전까지 임의의 완료 노드를 표시하지 않습니다.</p></div>}
              <div className="canvas-caption"><span className="caption-dot"/>
                {view === 'overview' ? '그룹 클릭 → 세부 기능 104개 탐색' : '기능 노드 클릭 → 입력·결과·작업 이력'}
              </div>
            </div>
            <Console open={consoleOpen} setOpen={setConsoleOpen} job={activeJob}
              jobError={jobError} selectedNumber={selectedNumber}
              onRefresh={() => { refresh(true); if (selectedNumber) { loadInspector(selectedNumber, true); loadRuns(selectedNumber); }}}/>
          </section>
          <Inspector context={context} catalog={catalog} view={view}
            selectedNumber={selectedNumber} detail={inspector} detailLoading={inspectBusy}
            detailError={inspectError} tab={tab} setTab={setTab} params={params}
            setParams={setParams} token={token} setToken={setToken}
            onInspect={() => { if (selectedNumber) loadInspector(selectedNumber, true); }}
            onRun={runOne} actionBusy={actionBusy} actionError={actionError}
            job={activeJob} runs={runs} runsLoading={runsLoading}
            onFeature={openFeature} runHistory={runHistory}
            collapse={collapsedInspector} setCollapse={setCollapsedInspector}/>
        </div>
        <div className="page-footer"><ShieldCheck size={16}/>
          API 실행 요청과 검증 완료는 다릅니다. 입찰참가 버튼 클릭·전자서명·투찰 제출은 수행하지 않습니다.
          <span>ProcureFlow Workflow Studio</span></div>
      </div>
    </div>
  </div>;
}

export default function App() {
  return <ReactFlowProvider><StudioApp/></ReactFlowProvider>;
}
