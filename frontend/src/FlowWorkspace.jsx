import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, ArrowLeft, BookOpen, CheckCircle2, ChevronDown, ChevronLeft,
  ChevronRight, ExternalLink, FileText, GitBranch, Layers, List,
  LoaderCircle, LockKeyhole, Maximize2, Minimize2, PanelLeftClose,
  PanelRightClose, PanelRightOpen, RefreshCw, Search, SlidersHorizontal,
  TerminalSquare, X,
} from 'lucide-react';
import { GROUPS } from './workflow.js';
import { SELECTED_BID } from './api.js';
import { clampInspectorWidth, visibleFlowFeatures } from './flowWorkspace.js';
import './flowWorkspace.css';

/**
 * Standalone full-viewport workflow workspace.
 *
 * The graph is deliberately the entire working surface. There are NO legacy
 * side menus, dashboard cards or embedded iframe. Library, API inspector and
 * execution console are dismissible overlays; optionally dock the inspector
 * for side-by-side testing. Execution remains in existing FastAPI/Worker.
 */
export default function FlowWorkspace({
  catalog, catalogBusy, catalogError, context, lastRead,
  view, selectedNumber, onGroup, onFeature, onNodeClick, onRefresh,
  plan, planError, job, consoleOpen, setConsoleOpen,
  renderCanvas, renderInspector, renderConsole,
}) {
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorDocked, setInspectorDocked] = useState(false);
  const [inspectorWidth, setInspectorWidth] = useState(540);
  const [search, setSearch] = useState('');
  const [browserFullscreen, setBrowserFullscreen] = useState(false);
  const [fullScreenError, setFullScreenError] = useState('');
  const [consoleTall, setConsoleTall] = useState(false);
  const librarySearch = useRef(null);
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);

  const effectiveWidth = clampInspectorWidth(inspectorWidth, viewportWidth);
  const matchingFeatures = useMemo(
    () => visibleFlowFeatures(catalog, search), [catalog, search],
  );
  const verifiedCount = catalog.filter((f) => f.acceptance_state === 'verified').length;

  useEffect(() => {
    const update = () => setViewportWidth(window.innerWidth);
    const fullscreenChanged = () => setBrowserFullscreen(!!document.fullscreenElement);
    window.addEventListener('resize', update);
    document.addEventListener('fullscreenchange', fullscreenChanged);
    return () => {
      window.removeEventListener('resize', update);
      document.removeEventListener('fullscreenchange', fullscreenChanged);
    };
  }, []);

  useEffect(() => {
    if (selectedNumber) {
      setInspectorOpen(true);
      setLibraryOpen(false);
    }
  }, [selectedNumber]);

  useEffect(() => {
    if (libraryOpen) librarySearch.current?.focus();
  }, [libraryOpen]);

  useEffect(() => {
    const shortcut = (event) => {
      const tag = document.activeElement?.tagName?.toLowerCase();
      if (event.key === 'Escape') {
        if (libraryOpen || inspectorOpen) {
          setLibraryOpen(false);
          setInspectorOpen(false);
          event.stopPropagation();
        }
      }
      if (event.ctrlKey || event.metaKey || event.altKey || tag === 'input' ||
          tag === 'textarea' || tag === 'select' || event.repeat) return;
      if (event.key === '[') { setLibraryOpen((value) => !value); event.preventDefault(); }
      if (event.key === ']') { setInspectorOpen((value) => !value); event.preventDefault(); }
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, [libraryOpen, inspectorOpen]);

  const chooseGroup = useCallback((key) => {
    onGroup(key);
    setLibraryOpen(false);
    setInspectorOpen(false);
  }, [onGroup]);

  const chooseFeature = useCallback((number) => {
    onFeature(number);
    setInspectorOpen(true);
    setLibraryOpen(false);
  }, [onFeature]);

  const clickNode = useCallback((id) => {
    onNodeClick(id);
    if (id.startsWith('feature:')) {
      setInspectorOpen(true);
      setLibraryOpen(false);
    } else if (id.startsWith('group:') || id === 'tender') {
      setInspectorOpen(false);
    }
  }, [onNodeClick]);

  const toggleFullscreen = async () => {
    setFullScreenError('');
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen();
      else setFullScreenError('이 브라우저는 전체화면 API를 지원하지 않습니다. 브라우저의 전체화면 기능을 사용하세요.');
    } catch (error) {
      setFullScreenError(error.message || '브라우저 전체화면 전환이 허용되지 않았습니다.');
    }
  };

  // Dynamically resize the panel without modifying graph positions or
  // storing sensitive execution data in the browser.
  const startResize = (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const initial = event.clientX;
    const original = effectiveWidth;
    const move = (e) => {
      setInspectorWidth(clampInspectorWidth(original + initial - e.clientX, window.innerWidth));
    };
    const stop = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop);
    window.addEventListener('pointercancel', stop);
  };

  const selected = catalog.find((f) => f.number === selectedNumber);
  const recommended = plan?.recommended_next;
  const recommendedNumber = recommended?.feature_no;
  const compactWorkflowName = view === 'overview'
    ? '전체 흐름' : (GROUPS.find((g) => g.key === view)?.title || '선택 업무 그룹');

  return <div className="flow-workspace" style={{ '--flow-panel-width': effectiveWidth + 'px' }}>
    <header className="flow-workspace-topbar">
      <div className="flow-workspace-brand">
        <span className="flow-workspace-logo"><GitBranch size={20} /></span>
        <div className="flow-workspace-name"><strong>ProcureFlow</strong>
          <small>FLOW WORKSPACE · 독립 작업실</small></div>
        <span className="flow-workspace-divider" />
        <div className="flow-workspace-active-case" title={context?.title || ''}>
          <span>발주정보</span><strong>{context?.bid_no || SELECTED_BID}</strong>
          <span className="flow-workspace-case-title">{context?.title || '발주 원본 조회 중'}</span>
        </div>
      </div>
      <div className="flow-workspace-top-actions">
        <div className="flow-workspace-verified" title="실제 증빙이 있는 기능 수">
          <CheckCircle2 size={14}/><strong>{catalog.length ? verifiedCount : '—'}</strong><span>/ 104 검증</span>
        </div>
        <button className="flow-action" onClick={onRefresh} disabled={catalogBusy} title="최신 DB 결과 새로고침">
          <RefreshCw size={16} className={catalogBusy ? 'spinning' : ''}/><span>새로고침</span></button>
        <button className="flow-action" onClick={toggleFullscreen}
          aria-label={browserFullscreen ? '브라우저 전체화면 종료' : '브라우저 전체화면'}
          title="브라우저 전체화면 전환">
          {browserFullscreen ? <Minimize2 size={17}/> : <Maximize2 size={17}/>}
          <span>{browserFullscreen ? '전체화면 종료' : '전체화면'}</span></button>
        <a href="/" className="flow-action flow-return" title="메인 운영 화면으로 이동"><ArrowLeft size={16}/><span>메인으로</span></a>
      </div>
    </header>

    <section className={`flow-workspace-stage ${inspectorOpen && inspectorDocked ? 'flow-is-docked' : ''}`}
      aria-label="독립된 워크플로 캔버스">
      <div className="flow-workspace-canvas">
        {catalog.length ? renderCanvas(clickNode) :
          <div className="flow-workspace-loading">
            {catalogBusy ? <LoaderCircle size={25} className="spinning"/> : <Layers size={25}/>}
            <strong>{catalogBusy ? '104개 업무 노드 불러오는 중…' : '워크플로를 조회하지 못했습니다.'}</strong>
            <p>{catalogError || '원본 데이터 조회 중입니다.'}</p>
            {!catalogBusy && <button className="flow-action" onClick={onRefresh}>다시 시도</button>}
          </div>}
      </div>

      <div className="flow-workspace-floatbar" role="toolbar" aria-label="워크플로 작업 도구">
        <button className={`flow-tool ${libraryOpen ? 'active' : ''}`}
          onClick={() => setLibraryOpen((open) => !open)} aria-expanded={libraryOpen}
          title="104개 기능 목록 열기 ([)">
          {libraryOpen ? <PanelLeftClose size={17}/> : <List size={17}/>}<span>노드 목록</span>
        </button>
        <span className="flow-tool-separator"/>
        {view !== 'overview' && <button className="flow-tool" onClick={() => chooseGroup('overview')}>
          <ChevronLeft size={16}/>전체</button>}
        <label className="flow-group-picker">
          <span className="sr-only">워크플로 그룹 선택</span>
          <select value={view} onChange={(event) => chooseGroup(event.target.value)}>
            <option value="overview">전체 흐름</option>
            {GROUPS.map((group) => <option key={group.key} value={group.key}>
              {group.title} ({group.range[1] - group.range[0] + 1})
            </option>)}
          </select>
          <ChevronDown size={14}/>
        </label>
        <span className="flow-tool-separator"/>
        <button className={`flow-tool ${inspectorOpen ? 'active' : ''}`}
          onClick={() => { setInspectorOpen((open) => !open); setLibraryOpen(false); }}
          aria-expanded={inspectorOpen} title="입력·출력 및 노드 단독 API 테스트 (])">
          <SlidersHorizontal size={17}/><span>노드 검사</span>
        </button>
        <button className={`flow-tool ${consoleOpen ? 'active' : ''}`}
          onClick={() => setConsoleOpen(!consoleOpen)} aria-expanded={consoleOpen}
          title="API 실행 로그 열기">
          <TerminalSquare size={17}/><span>실행 로그</span>
          {job && <span className="flow-tiny-active"/>}
        </button>
      </div>

      <div className="flow-workspace-context" role="status">
        <span><span className="flow-workspace-green-dot"/> {compactWorkflowName}</span>
        <span className="flow-context-divider"/>
        <span>선택 노드: {selected ? '#' + selected.number : '없음'}</span>
        {lastRead && <span className="flow-workspace-last-read">DB 업데이트 확인됨</span>}
      </div>

      {planError && <div className="flow-workspace-warning" role="alert">{planError}</div>}
      {fullScreenError && <div className="flow-workspace-fullscreen-error" role="alert">{fullScreenError}</div>}
      {catalogError && catalog.length > 0 && <div className="flow-workspace-warning" role="alert">최신 DB 조회 오류: {catalogError}</div>}

      {recommendedNumber && <button className="flow-workspace-next" onClick={() => chooseFeature(recommendedNumber)}
        title="추천 단계를 개별 검사 패널에서 확인">
        <span>다음 추천 노드</span><strong>#{recommendedNumber} · {recommended?.group || ''}</strong>
        <ChevronRight size={15}/>
      </button>}

      {libraryOpen && <aside className="flow-workspace-library" aria-label="104개 기능 노드 선택">
        <div className="flow-workspace-drawer-head">
          <div><strong>노드 라이브러리</strong><small>104개 API 기능 · 선택하면 검사 패널 열림</small></div>
          <button className="flow-workspace-icon" aria-label="노드 목록 닫기"
            onClick={() => setLibraryOpen(false)}><X size={18}/></button>
        </div>
        <div className="flow-workspace-search"><Search size={16}/><input
          ref={librarySearch} value={search} onChange={(e) => setSearch(e.target.value)}
          type="search" placeholder="노드 번호 또는 기능명 검색" aria-label="104개 기능 검색"/></div>
        <div className="flow-workspace-group-list">
          <button className={view === 'overview' ? 'current' : ''}
            onClick={() => chooseGroup('overview')}><Layers size={16}/>전체 흐름<ChevronRight size={15}/></button>
          {GROUPS.map((group) => <button key={group.key}
            className={view === group.key ? 'current' : ''}
            onClick={() => chooseGroup(group.key)}>
            <GitBranch size={15}/>{group.title}
            <small>{group.range[0]}–{group.range[1]}</small></button>)}
        </div>
        <div className="flow-workspace-drawer-caption">
          <span>API 기능</span><span>{matchingFeatures.length} / 104</span></div>
        <div className="flow-workspace-library-list">
          {matchingFeatures.map((feature) => <button key={feature.number}
            onClick={() => chooseFeature(feature.number)}
            className={selectedNumber === feature.number ? 'selected' : ''}>
            <span className="flow-feature-index">#{String(feature.number).padStart(3, '0')}</span>
            <span className="flow-feature-name">{feature.name}</span>
            <span className={`flow-feature-status ${feature.acceptance_state || 'missing'}`}/>
          </button>)}
          {!matchingFeatures.length && <p className="flow-workspace-no-results">일치하는 기능이 없습니다.</p>}
        </div>
      </aside>}

      {inspectorOpen && <aside className="flow-workspace-inspector-frame"
        aria-label="노드 API 입력, 출력 및 실행 검사">
        <div className="flow-workspace-resize" role="separator" aria-label="노드 검사 패널 크기 변경"
          aria-orientation="vertical" onPointerDown={startResize} title="끌어서 패널 너비 조절"/>
        <div className="flow-workspace-inspector-controls">
          <strong><SlidersHorizontal size={15}/> 노드 API · 결과 · 이력</strong>
          <div className="flow-workspace-inspector-buttons">
            <button className="flow-workspace-icon" onClick={() => setInspectorDocked((value) => !value)}
              aria-label={inspectorDocked ? '캔버스 위 오버레이로 표시' : '캔버스 옆에 고정'}
              title={inspectorDocked ? '패널 분리' : '캔버스 옆에 고정'}>
              {inspectorDocked ? <PanelRightOpen size={17}/> : <PanelRightClose size={17}/>}
            </button>
            <button className="flow-workspace-icon" onClick={() =>
              setInspectorWidth((current) => current >= 750 ? 500 : 820)}
              aria-label="검사 패널 너비 확대/축소" title="넓은 결과 패널 전환">
              <Maximize2 size={16}/></button>
            <button className="flow-workspace-icon" onClick={() => setInspectorOpen(false)}
              aria-label="검사 패널 닫기"><X size={18}/></button>
          </div>
        </div>
        <div className="flow-workspace-inspector-content">{renderInspector(() => setInspectorOpen(false))}</div>
      </aside>}

      {consoleOpen && <div className={`flow-workspace-console ${consoleTall ? 'expanded' : ''} ${inspectorOpen && inspectorDocked ? 'with-dock' : ''}`}>
        <div className="flow-console-controls">
          <span><Activity size={14}/>독립 실행 콘솔 · 실제 Worker 결과</span>
          <div>
            <button className="flow-workspace-icon" onClick={() => setConsoleTall((value) => !value)}
              title={consoleTall ? '로그 높이 줄이기' : '로그 크게 보기'} aria-label="실행 로그 크기 변경">
              {consoleTall ? <Minimize2 size={16}/> : <Maximize2 size={16}/>}</button>
            <button className="flow-workspace-icon" onClick={() => setConsoleOpen(false)}
              title="로그 닫기" aria-label="실행 로그 닫기"><X size={16}/></button>
          </div>
        </div>
        {renderConsole()}
      </div>}

      <div className="flow-workspace-safety" title="기존 실행 엔진에서는 연결선 편집과 병렬 조건 설정이 아직 구현되지 않았습니다.">
        <LockKeyhole size={12}/><span>발주 원본 기반 API 검사 · 입찰 제출 없음</span>
      </div>
    </section>
  </div>;
}
