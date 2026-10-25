import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ReactFlow, Background, Controls, MiniMap, addEdge,
  reconnectEdge, useNodesState, useEdgesState,
} from '@xyflow/react';
import {
  AlertCircle, ArrowLeft, Check, ChevronDown, GitBranch,
  Layers, LoaderCircle, LockKeyhole, Network, Pause,
  Pin, Play, Plus, RefreshCw, RotateCcw, Save, Search,
  SkipForward, Square, Trash2, X, Zap,
} from 'lucide-react';
import { api, SELECTED_BID } from './api.js';
import './dagEditor.css';

const MODES = ['all','any','quorum','all_settled'];
const CONDITIONS = ['success','failure','always','skipped'];
const safeId = () => 'n-' + crypto.randomUUID().replaceAll('-','').slice(0,16);

function useAsGraph(nodes, edges, description = '') {
  return useMemo(() => ({
    nodes:nodes.map(n=>({
      id:n.id, type:n.data.kind, label:n.data.title,
      feature_no:n.data.kind === 'feature' ? Number(n.data.feature_no || 1) : null,
      position:{ x:Math.round(n.position.x),y:Math.round(n.position.y) },
      join:n.data.join || { mode:'all' },
      breakpoint_before:!!n.data.before,breakpoint_after:!!n.data.after,
    })),
    edges:edges.map(e=>({
      id:e.id,source:e.source,target:e.target,
      when:e.data?.when || 'success',mapping:e.data?.mapping || {},
    })),
    description,
  }),[nodes,edges,description]);
}

function graphToVisual(graph) {
  return {
    nodes:(graph.nodes || []).map(n=>({
      id:n.id,position:n.position, type:'default', draggable:n.type!=='start',
      deletable:n.type!=='start',data:{
        title:n.label,kind:n.type,feature_no:n.feature_no,
        join:n.join||{mode:'all'},before:!!n.breakpoint_before,after:!!n.breakpoint_after,
      },
    })),
    edges:(graph.edges||[]).map(e=>({
      id:e.id,source:e.source,target:e.target,type:'smoothstep',
      data:{when:e.when||'success',mapping:e.mapping||{}},
    })),
  };
}
function NodeFace({ node, debug }) {
  const status = debug?.result?.node_states?.[node.id] || 'not-run';
  return <div className="dag-face">
    <div className="dag-face-heading"><span>{node.data.kind.toUpperCase()}</span>
      <span className={'dag-tiny-state state-'+status}>{status}</span></div>
    <strong>{node.data.title || node.id}</strong>
    {node.data.kind==='feature' && <small>API #{String(node.data.feature_no).padStart(3,'0')}</small>}
    {node.data.kind==='join' && <small>JOIN {node.data.join?.mode || 'all'}</small>}
    {(node.data.before||node.data.after) && <small className="dag-breakpoint">● Breakpoint</small>}
  </div>;
}

export default function DAGEditor({ catalog, token, setToken, onExit }) {
  const [designs,setDesigns]=useState([]);
  const [designId,setDesignId]=useState('');
  const [designName,setDesignName]=useState('새 워크플로');
  const [revision,setRevision]=useState(0);
  const [published,setPublished]=useState(false);
  const [nodes,setNodes,onNodesChange]=useNodesState([]);
  const [edges,setEdges,onEdgesChange]=useEdgesState([]);
  const [description,setDescription]=useState('');
  const [selectedNode,setSelectedNode]=useState(null);
  const [selectedEdge,setSelectedEdge]=useState(null);
  const [debug,setDebug]=useState(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [message,setMessage]=useState('');
  const [search,setSearch]=useState('');
  const [fixture,setFixture]=useState('{"status":"test_ok"}');
  const [mappingDraft,setMappingDraft]=useState('{}');
  const [debugView,setDebugView]=useState('settings');
  const graph=useAsGraph(nodes,edges,description);
  const activeNode=nodes.find(n=>n.id===selectedNode);
  const activeEdge=edges.find(e=>e.id===selectedEdge);
  useEffect(()=>{setMappingDraft(JSON.stringify(activeEdge?.data?.mapping||{},null,2));},[selectedEdge]);
  const matching = catalog.filter(f=>
    (String(f.number)+' '+f.name).toLocaleLowerCase().includes(search.toLocaleLowerCase().trim())).slice(0,104);

  const openDesign=useCallback(async (id) => {
    if(!id)return;
    setBusy(true);setError('');
    try {
      const item=await api.loadWorkflowDesign(id,token);
      const shape=graphToVisual(item.graph);
      setNodes(shape.nodes);setEdges(shape.edges);
      setDescription(item.graph.description||'');
      setDesignId(item.id);setDesignName(item.name);
      setRevision(item.revision);setPublished(item.status==='published');
      setSelectedNode(null);setSelectedEdge(null);setDebug(null);
    } catch(e){setError(e.message);} finally {setBusy(false);}
  },[token,setNodes,setEdges]);

  const reloadDesigns=useCallback(async () => {
    if(!token?.trim())return;
    try {
      const result=await api.workflowDesigns(token);
      setDesigns(result.designs||[]);
    }catch(e){setError(e.message);}
  },[token]);

  useEffect(()=>{reloadDesigns();},[reloadDesigns]);

  const createDesign=async()=>{
    if(!token?.trim()){setError('관리자 토큰을 입력하세요.');return;}
    setBusy(true);setError('');
    try {
      const data=await api.createWorkflowDesign('새 발주정보 워크플로',null,token);
      await reloadDesigns();
      await openDesign(data.id);
      setMessage('신규 워크플로를 생성했습니다. 노드·연결선을 수정한 후 저장하세요.');
    }catch(e){setError(e.message);}finally{setBusy(false);}
  };
  const saveDesign=async(publish=false)=>{
    if(!designId){setError('먼저 신규 워크플로를 생성하거나 기존 것을 불러오세요.');return;}
    setBusy(true);setError('');
    try {
      const saved=await api.saveWorkflowDesign(designId,revision,designName,graph,publish,token);
      setRevision(saved.revision);setPublished(saved.status==='published');
      setMessage(publish?'DAG 검증 후 버전을 게시했습니다.':'수정한 노드와 연결선을 DB에 저장했습니다.');
      await reloadDesigns();
    }catch(e){setError(e.message);}finally{setBusy(false);}
  };
  const deleteDesign=async()=>{
    if(!designId)return;
    if(!window.confirm('이 워크플로를 보관처리할까요? 기존 디버그 이력은 남습니다.'))return;
    setBusy(true);setError('');
    try{
      await api.deleteWorkflowDesign(designId,token);
      setDesignId('');setNodes([]);setEdges([]);setDebug(null);setSelectedNode(null);
      await reloadDesigns();
      setMessage('워크플로를 보관처리했습니다.');
    }catch(e){setError(e.message);}finally{setBusy(false);}
  };

  const addNode=(kind='feature',number=1)=>{
    const f=catalog.find(item=>item.number===number);
    const id=safeId();
    setNodes(old=>[...old,{
      id,type:'default',position:{x:300+((old.length%4)*280),y:100+(Math.floor(old.length/4)*160)},
      data:{title:kind==='feature'?(f?.name || '기능 '+number):
            kind==='join'?'합류 노드':kind==='condition'?'조건 노드':'메모',
            kind,feature_no:kind==='feature'?number:null,
            join:{mode:'all'},before:false,after:false},
    }]);
    setSelectedNode(id);setSelectedEdge(null);setMessage('노드가 추가됐습니다. 연결선으로 흐름을 연결하세요.');
  };
  const deleteSelected=()=>{
    if(selectedNode){
      if(nodes.find(n=>n.id===selectedNode)?.data.kind==='start'){setError('발주 시작 노드는 삭제할 수 없습니다.');return;}
      setNodes(old=>old.filter(n=>n.id!==selectedNode));
      setEdges(old=>old.filter(e=>e.source!==selectedNode&&e.target!==selectedNode));
      setSelectedNode(null);
    }else if(selectedEdge){setEdges(old=>old.filter(e=>e.id!==selectedEdge));setSelectedEdge(null);}
  };
  const updateNode=(key,value)=>{
    setNodes(old=>old.map(n=>n.id===selectedNode?{
      ...n,data:{...n.data,[key]:value},
    }:n));
  };
  const updateEdge=(key,value)=>{
    setEdges(old=>old.map(e=>e.id===selectedEdge?{
      ...e,data:{...e.data,[key]:value},
    }:e));
  };
  const onConnect=useCallback((connection)=>{
    if(connection.source===connection.target)return;
    setEdges(old=>addEdge({id:safeId(),...connection,type:'smoothstep',
      data:{when:'success',mapping:{}}},old));
  },[setEdges]);
  const onReconnect=useCallback((oldEdge,connection)=>{
    setEdges(old=>reconnectEdge(oldEdge,connection,old));
  },[setEdges]);

  const startDebug=async()=>{
    if(!designId||!published){setError('먼저 연결된 그래프를 게시해야 합니다.');return;}
    setBusy(true);setError('');
    try {
      const result=await api.createWorkflowDebug(designId,token);
      setDebug(result);setDebugView('debug');
      setMessage('테스트 전용 단계별 실행을 시작했습니다. 외부 수집·투찰은 실행되지 않습니다.');
    }catch(e){setError(e.message);}finally{setBusy(false);}
  };
  const command=async(action)=>{
    if(!debug?.id){setError('먼저 디버그 실행을 시작하세요.');return;}
    setBusy(true);setError('');
    try{
      const nodeId = ['pin','fail','skip','retry'].includes(action) ? selectedNode : null;
      if(['pin','fail','skip','retry'].includes(action)&&!nodeId)throw new Error('대상 노드를 선택하세요.');
      let payload=null;
      if(action==='pin')payload=JSON.parse(fixture);
      if(action==='fail')payload='simulated failure';
      const next=await api.workflowDebugAction(debug.id,action,nodeId,payload,token);
      setDebug(next);
      setDebugView('debug');
      setMessage('디버그 작업: '+action+' · 실제 수집기가 실행된 것은 아닙니다.');
    }catch(e){setError(e.message);}finally{setBusy(false);}
  };
  const displayedNodes=useMemo(()=>nodes.map(n=>({
    ...n,data:{...n.data,label:<NodeFace node={n} debug={debug}/>},
    style:{border:n.id===selectedNode?'2px solid #328fa5':'1px solid #b7cbd9',
      borderRadius:10,background:'#fff',padding:0,minWidth:185},
  })),[nodes,debug,selectedNode]);
  const displayedEdges=useMemo(()=>edges.map(e=>({
    ...e,style:{stroke:e.id===selectedEdge?'#20a098':'#8fa9c0',strokeWidth:e.id===selectedEdge?3:2},
    label:e.data?.when==='success'?'':(e.data?.when||''),
  })),[edges,selectedEdge]);

  return <div className="dag-studio">
    <header className="dag-topbar">
      <div className="dag-brand"><Network size={20}/><strong>ProcureFlow Flow Designer</strong>
        <small>선택 발주 {SELECTED_BID} · 독립 편집/디버깅</small></div>
      <div className="dag-top-actions">
        <button className="button secondary" onClick={onExit}><ArrowLeft size={15}/>조회 화면으로</button>
        <button className="button secondary" onClick={createDesign} disabled={busy}><Plus size={14}/>새 워크플로</button>
        <button className="button secondary" disabled={!designId||busy}
          onClick={()=>saveDesign(false)}><Save size={14}/>초안 저장</button>
        <button className="button primary" disabled={!designId||busy}
          onClick={()=>saveDesign(true)}><Check size={14}/>버전 게시</button>
      </div>
    </header>
    <div className="dag-workspace">
      <aside className="dag-palette">
        <div className="dag-section-heading">WORKFLOW</div>
        <select value={designId} onChange={e=>openDesign(e.target.value)}>
          <option value="">워크플로 선택…</option>
          {designs.map(d=><option key={d.id} value={d.id}>{d.name} (v{d.revision})</option>)}
        </select>
        <label>이름<input value={designName} onChange={e=>setDesignName(e.target.value)}
          maxLength={140}/></label>
        <div className="dag-version">{designId?'v'+revision:'미저장'} · {published?'게시됨':'초안'}</div>
        <div className="dag-section-heading">노드 추가</div>
        <input type="search" value={search} onChange={e=>setSearch(e.target.value)}
          placeholder="104개 기능 검색"/>
        <div className="dag-palette-items">
          {matching.map(f=><button key={f.number} onClick={()=>addNode('feature',f.number)}>
            <span>#{String(f.number).padStart(3,'0')}</span>{f.name}</button>)}
        </div>
        <button className="dag-add-utility" onClick={()=>addNode('join')}><Plus size={15}/>AND / ANY / QUORUM 합류</button>
        <button className="dag-add-utility" onClick={()=>addNode('condition')}><Plus size={15}/>조건 노드</button>
        <button className="dag-add-utility" onClick={()=>addNode('note')}><Plus size={15}/>설명·주석</button>
        <div className="dag-palette-bottom">시작점은 발주정보 1건입니다. 변경사항은 저장해야 반영됩니다.</div>
      </aside>
      <main className="dag-canvas">
        <div className="dag-hint">노드 이동 · 포트 드래그로 연결 · 연결선 선택 후 조건 설정 · 저장/게시</div>
        {nodes.length?<ReactFlow nodes={displayedNodes} edges={displayedEdges}
          onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
          onConnect={onConnect} onReconnect={onReconnect}
          nodesConnectable nodesDraggable edgesReconnectable
          onNodeClick={(_,n)=>{setSelectedNode(n.id);setSelectedEdge(null);}}
          onEdgeClick={(_,e)=>{setSelectedEdge(e.id);setSelectedNode(null);}}
          fitView minZoom={.2} maxZoom={2}>
          <Background color="#d4e1ec" gap={22}/>
          <Controls/><MiniMap/>
        </ReactFlow>:<div className="dag-placeholder"><Layers size={29}/>
          <strong>저장된 워크플로를 선택하거나 새 워크플로를 생성하세요.</strong></div>}
      </main>
      <aside className="dag-editor-panel">
        <div className="dag-panel-head">
          <strong>{debugView==='debug'?'Debugger':'노드 / 연결선 편집'}</strong>
          <div><button className={debugView==='settings'?'selected':''}
            onClick={()=>setDebugView('settings')}>설정</button>
          <button className={debugView==='debug'?'selected':''}
            onClick={()=>setDebugView('debug')}>디버그</button></div>
        </div>
        <div className="dag-panel-scroll">
          <label>관리자 토큰<input type="password" autoComplete="off" placeholder="필수 인증"
            value={token || ''} onChange={e=>setToken(e.target.value)}/></label>
          {debugView==='settings'?<>
            {activeNode?<div className="dag-form">
              <div className="dag-selection">선택 노드 · {activeNode.id}</div>
              <label>이름<input value={activeNode.data.title||''}
                onChange={e=>updateNode('title',e.target.value)}/></label>
              <label>노드 유형<input value={activeNode.data.kind} readOnly/></label>
              {activeNode.data.kind==='feature'&&<label>연결된 API 번호
                <select value={activeNode.data.feature_no}
                  onChange={e=>updateNode('feature_no',Number(e.target.value))}>
                  {catalog.map(f=><option value={f.number} key={f.number}>{f.number} · {f.name}</option>)}
                </select></label>}
              <label>합류 조건
                <select value={activeNode.data.join?.mode||'all'}
                  onChange={e=>updateNode('join',{...activeNode.data.join,mode:e.target.value})}>
                  {MODES.map(x=><option key={x} value={x}>{x}</option>)}
                </select></label>
              {activeNode.data.join?.mode==='quorum'&&<label>최소 성공 개수
                <input type="number" min={1} max={250}
                  value={activeNode.data.join.minimum||1}
                  onChange={e=>updateNode('join',{...activeNode.data.join,minimum:Number(e.target.value)})}/>
              </label>}
              <label className="dag-check"><input type="checkbox" checked={activeNode.data.before}
                onChange={e=>updateNode('before',e.target.checked)}/>실행 전 브레이크포인트</label>
              <label className="dag-check"><input type="checkbox" checked={activeNode.data.after}
                onChange={e=>updateNode('after',e.target.checked)}/>실행 후 브레이크포인트</label>
              {activeNode.data.kind!=='start'&&<button className="dag-delete" onClick={deleteSelected}>
                <Trash2 size={15}/>선택 노드 삭제</button>}
            </div>:activeEdge?<div className="dag-form">
              <div className="dag-selection">연결선 · {activeEdge.id}</div>
              <div className="dag-path">{activeEdge.source} → {activeEdge.target}</div>
              <label>연결 조건
                <select value={activeEdge.data?.when||'success'}
                  onChange={e=>updateEdge('when',e.target.value)}>
                  {CONDITIONS.map(x=><option key={x} value={x}>{x}</option>)}
                </select></label>
              <label>출력 → 입력 경로 매핑 (JSON)
                <textarea rows={5} value={mappingDraft}
                  onChange={e=>setMappingDraft(e.target.value)}/>
              </label>
              <button className="button secondary" onClick={()=>{
                try{
                  const parsed=JSON.parse(mappingDraft);
                  if(!parsed||Array.isArray(parsed)||typeof parsed!=='object')
                    throw new Error('JSON 객체만 허용합니다.');
                  updateEdge('mapping',parsed);
                  setError('');setMessage('선 연결의 입력·출력 경로가 수정되었습니다. 초안 저장을 눌러 적용하세요.');
                }catch(e){setError('입출력 경로 매핑 오류: '+e.message);}
              }}>입출력 매핑 적용</button>
              <button className="dag-delete" onClick={deleteSelected}>
                <Trash2 size={15}/>연결선 삭제</button>
            </div>:<div className="dag-placeholder-text">노드 또는 선을 선택하면 세부 연결과 조건을 편집할 수 있습니다.</div>}
          </>:<>
            <div className="dag-warning">**시뮬레이션 전용** — 실제 나라장터 수집·투찰 및 Worker 병렬 실행은 수행하지 않습니다.</div>
            <button className="button primary dag-wide" disabled={!published||busy||!token}
              onClick={startDebug}><Play size={15}/>새 디버그 실행</button>
            {debug&&<>
              <div className="dag-debug-state">
                <strong>{debug.result?.status || 'paused'}</strong>
                <span>STEP {debug.result?.steps_completed || 0}</span>
              </div>
              <div className="dag-debug-controls">
                {[
                  ['step','한 단계',Play],['continue','계속',Zap],['pause','일시정지',Pause],
                  ['resume','재개',RotateCcw],['stop','중지',Square],
                  ['skip','건너뛰기',SkipForward],['retry','재시도',RotateCcw],
                ].map(([action,label,Icon])=><button key={action}
                  onClick={()=>command(action)} disabled={busy}>
                  <Icon size={14}/>{label}</button>)}
              </div>
              <label>선택 노드 테스트 출력(JSON)<textarea rows={6}
                value={fixture} onChange={e=>setFixture(e.target.value)}/></label>
              <div className="dag-debug-controls">
                <button disabled={!selectedNode||busy} onClick={()=>command('pin')}>
                  <Pin size={14}/>출력 고정</button>
                <button disabled={!selectedNode||busy} onClick={()=>command('fail')}>
                  <AlertCircle size={14}/>실패 주입</button>
              </div>
              <div className="dag-debug-list">다음 실행 가능 노드:
                <strong>{(debug.result?.ready_nodes||[]).join(', ')||'없음'}</strong></div>
              <pre className="dag-result-json">{JSON.stringify(debug.result,null,2)}</pre>
            </>}
          </>}
          {error&&<div className="dag-error" role="alert">{error}</div>}
          {message&&<div className="dag-info">{message}</div>}
        </div>
        <div className="dag-panel-foot"><LockKeyhole size={14}/>저장 버전과 실행 스냅샷 분리</div>
      </aside>
    </div>
  </div>;
}
