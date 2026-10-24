import { useCallback, useEffect, useRef, useState } from 'react';
import {
  CheckCircle2, AlertCircle, UploadCloud, Play, LoaderCircle,
  FileText, Download, FilePlus2, Save, Pin, History,
  ChevronDown, RotateCcw, Trash2, Braces, ShieldAlert,
} from 'lucide-react';
import { api, uploadNodeTestFile } from './api.js';
import './nodeLab.css';

function jsonString(value) { return JSON.stringify(value, null, 2); }
const MODES = [
  { value: 'official', title: '공식 DB 관측', help: '선택한 발주정보의 저장된 원본 조회만 수행. 수집기 변경 없음' },
  { value: 'manual', title: '직접 JSON', help: '직접 입력한 변수를 검증하는 테스트. 실제 업무 API가 실행된 것으로 보지 않음' },
  { value: 'file', title: '테스트 파일', help: 'PDF/HWP/HWPX/DOCX/XLSX/CSV 등의 실제 문서 파서 결과 확인' },
  { value: 'mock', title: '가상 응답', help: '가상 API 응답을 반환시켜 분기와 검증식의 결과 확인' },
];

function parseObject(text, message) {
  let data;
  try { data = JSON.parse(text || '{}'); } catch (err) {
    throw new Error(message + ': ' + err.message);
  }
  if (!data || Array.isArray(data) || typeof data !== 'object') {
    throw new Error(message + ': JSON object만 허용됩니다.');
  }
  return data;
}
function parseAssertions(text) {
  let list;
  try { list = JSON.parse(text || '[]'); } catch (err) {
    throw new Error('검증식 JSON: ' + err.message);
  }
  if (!Array.isArray(list) || list.length > 30) throw new Error('검증식은 최대 30개 배열입니다.');
  return list;
}
function FileChooser({ files, setFiles, disabled }) {
  const inputRef = useRef();
  const [dragging, setDragging] = useState(false);
  const add = (incoming) => {
    const list = Array.from(incoming || []);
    if (!list.length) return;
    setFiles((old) => [...old, ...list].slice(0, 6));
  };
  return <div className="node-lab-file-zone">
    <div className={'node-lab-drop ' + (dragging ? 'dragging' : '')}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); if (!disabled) add(e.dataTransfer.files); }}>
      <UploadCloud size={23}/>
      <strong>문서 드래그 앤 드롭</strong>
      <p>PDF · HWP · HWPX · DOCX · XLSX · CSV · TXT · JSON · XML</p>
      <button type="button" className="button secondary" disabled={disabled}
        onClick={() => inputRef.current?.click()}><FilePlus2 size={14}/>파일 선택</button>
      <input ref={inputRef} type="file" multiple style={{display:'none'}}
        accept=".pdf,.hwp,.hwpx,.docx,.xlsx,.csv,.txt,.json,.xml"
        onChange={(e) => { add(e.target.files); e.target.value = ''; }} />
    </div>
    {files.map((file, index) => <div className="node-lab-pending-file" key={file.name + index}>
      <FileText size={14}/>
      <span title={file.name}>{file.name}</span>
      <small>{Math.round(file.size / 1024)} KB</small>
      <button className="node-lab-icon-button" title="업로드 목록에서 빼기"
        onClick={() => setFiles((old) => old.filter((_,i) => i !== index))}><Trash2 size={13}/></button>
    </div>)}
  </div>;
}

export default function NodeLabPanel({ featureNo, token }) {
  const [mode,setMode] = useState('official');
  const [variables,setVariables] = useState('{\n  "test_input": "직접 입력한 테스트 데이터"\n}');
  const [mock,setMock] = useState('{\n  "status": "success",\n  "count": 1\n}');
  const [assertions,setAssertions] = useState('[]');
  const [files,setFiles] = useState([]);
  const [uploaded,setUploaded] = useState([]);
  const [chosenIds,setChosenIds] = useState([]);
  const [result,setResult] = useState(null);
  const [history,setHistory] = useState([]);
  const [pin,setPin] = useState(null);
  const [contract,setContract] = useState(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [tab,setTab] = useState('test');
  const activeToken = token?.trim() || '';

  const refreshData = useCallback(async () => {
    if (!featureNo || !activeToken) return;
    try {
      const [spec, uploadedFiles, runs, pinned] = await Promise.all([
        api.nodeTestContract(featureNo, activeToken),
        api.nodeTestFiles(featureNo, activeToken),
        api.nodeTestRuns(featureNo, activeToken),
        api.nodeTestPin(featureNo, activeToken),
      ]);
      setContract(spec);
      setUploaded(uploadedFiles.files || []);
      setHistory(runs.runs || []);
      setPin(pinned.pin);
    } catch (err) { setError(err.message); }
  }, [featureNo, activeToken]);

  useEffect(() => {
    setResult(null); setHistory([]); setUploaded([]); setChosenIds([]);
    setError(''); setPin(null);
    if (activeToken) refreshData();
  }, [featureNo, activeToken, refreshData]);

  const upload = async () => {
    if (!activeToken) { setError('관리자 토큰이 필요합니다.'); return; }
    if (!files.length) { setError('업로드할 파일을 선택하세요.'); return; }
    setBusy(true); setError('');
    try {
      let newIds = [];
      for (const file of files) {
        const returned = await uploadNodeTestFile(featureNo, file, activeToken);
        newIds.push(returned.id);
      }
      setFiles([]);
      setMode('file');
      setChosenIds(newIds);
      await refreshData();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  const execute = async () => {
    if (!activeToken) { setError('관리자 토큰이 필요합니다.'); return; }
    setBusy(true); setError('');
    try {
      const body = { mode, parameters: {}, assertions: parseAssertions(assertions) };
      if (mode === 'manual') body.variables = parseObject(variables, '수동 입력');
      if (mode === 'mock') body.mock_output = JSON.parse(mock);
      if (mode === 'file') {
        if (!chosenIds.length) throw new Error('실행할 파일을 선택하세요.');
        body.file_ids = chosenIds;
        body.variables = parseObject(variables, '수동 입력');
      }
      const reply = await api.nodeTest(featureNo, body, activeToken);
      setResult(reply);
      setTab('result');
      await refreshData();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  const pinOutput = async () => {
    if (!result) return;
    setBusy(true); setError('');
    try { await api.saveNodeTestPin(featureNo, result.output, 'node-' + featureNo + '-test', activeToken);
      await refreshData();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  const replay = (record) => {
    const original = record.request || {};
    setMode(original.mode || 'manual');
    setVariables(jsonString(original.variables || {}));
    setMock(jsonString(original.mock_output ?? {}));
    setAssertions(jsonString(original.assertions || []));
    setChosenIds(original.file_ids || []);
    setTab('test');
    setError('');
  };

  return <section className="node-lab">
    <div className="node-lab-banner">
      <ShieldAlert size={16}/>
      <div><strong>노드 독립 API 테스트 · #{String(featureNo).padStart(3,'0')}</strong>
        <p>수동 입력·업로드 파일은 테스트 전용입니다. 실제 발주 원본 증빙에 반영되지 않습니다.</p></div>
    </div>
    {!activeToken && <div className="node-lab-warning">
      위 설정 탭에서 관리자 토큰을 입력해야 테스트·파일 업로드·이력 조회가 가능합니다.
    </div>}
    <div className="node-lab-tabs">
      {['test','files','result','history'].map((id) => <button key={id}
        className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
        {{test:'입력·테스트',files:'파일',result:'출력',history:'이력·재현'}[id]}
      </button>)}
    </div>
    {tab === 'test' && <div className="node-lab-content">
      <label className="node-lab-label">입력 데이터 출처</label>
      <div className="node-lab-mode-grid">
        {MODES.map((option) => <button key={option.value}
          className={'node-lab-mode ' + (mode === option.value ? 'active' : '')}
          onClick={() => setMode(option.value)}><strong>{option.title}</strong>
          <span>{option.help}</span></button>)}
      </div>
      {['manual','file'].includes(mode) && <>
        <label className="node-lab-label" htmlFor="lab-variables">입력 변수 JSON</label>
        <textarea id="lab-variables" spellCheck={false}
          value={variables} onChange={(e) => setVariables(e.target.value)}/>
      </>}
      {mode === 'mock' && <>
        <label className="node-lab-label" htmlFor="lab-mock">가상 API 출력 JSON</label>
        <textarea id="lab-mock" spellCheck={false}
          value={mock} onChange={(e) => setMock(e.target.value)}/>
      </>}
      {mode === 'file' && <>
        <label className="node-lab-label">업로드된 테스트 파일 선택 (최대 6개)</label>
        {!uploaded.length && <div className="node-lab-warning">파일 탭에서 먼저 업로드하세요.</div>}
        {uploaded.map((file) => <label className="node-lab-check" key={file.id}>
          <input type="checkbox" checked={chosenIds.includes(file.id)}
            onChange={(e) => setChosenIds((old) => e.target.checked
              ? [...old, file.id].slice(0,6) : old.filter((id)=>id!==file.id))}/>
          <span>{file.filename}</span><small>{file.parse_state}</small>
        </label>)}
      </>}
      <label className="node-lab-label" htmlFor="lab-assertions">검증식 JSON (최대 30개)</label>
      <textarea id="lab-assertions" spellCheck={false} className="node-lab-short"
        value={assertions} onChange={(e) => setAssertions(e.target.value)}/>
      <small className="node-lab-hint">예: {jsonString([{path:'status',operator:'eq',expected:'success'}])}</small>
      <div className="node-lab-buttons">
        <button className="button primary" onClick={execute}
          disabled={busy || !activeToken}><Play size={15}/>{busy ? '실행 중…' : '현재 노드 테스트 실행'}</button>
        <button className="button secondary" onClick={refreshData} disabled={busy || !activeToken}>
          <RotateCcw size={15}/>새로고침</button>
      </div>
      <p className="node-lab-hint">공식 모드는 실제 DB 관측을 실행합니다. 직접 입력·파일·가상 모드는 테스트 전용이며 업무 수집기 실행과 구분됩니다.</p>
    </div>}
    {tab === 'files' && <div className="node-lab-content">
      <FileChooser files={files} setFiles={setFiles} disabled={busy || !activeToken}/>
      <div className="node-lab-buttons">
        <button className="button primary" disabled={busy || !activeToken || !files.length}
          onClick={upload}>{busy ? <LoaderCircle size={16} className="spinning"/> : <UploadCloud size={16}/>}테스트 파일 업로드</button>
      </div>
      <div className="node-lab-label">저장된 테스트 파일 ({uploaded.length})</div>
      {uploaded.map((item) => <div className="node-lab-uploaded" key={item.id}>
        <div><strong>{item.filename}</strong><small>{item.parse_state} · SHA {item.sha256?.slice(0,12)} · {item.size_bytes} bytes</small></div>
        <details><summary>분석된 텍스트 미리보기</summary>
          <pre className="node-lab-json">{item.text_preview || '추출된 텍스트 없음'}</pre></details>
      </div>)}
    </div>}
    {tab === 'result' && <div className="node-lab-content">
      {!result && <div className="node-lab-warning">현재 선택 기능의 테스트 결과가 없습니다.</div>}
      {result && <>
        <div className="node-lab-result-title">
          {result.assertions_passed ? <CheckCircle2 size={17}/> : <AlertCircle size={17}/>}
          <strong>{result.status}</strong>
          <span>{result.duration_ms} ms</span>
        </div>
        <div className="node-lab-label">반환된 출력 (검증 불가한 테스트 데이터)</div>
        <pre className="node-lab-json">{jsonString(result.output)}</pre>
        <div className="node-lab-label">검증식 실행 결과</div>
        <pre className="node-lab-json small">{jsonString(result.assertions)}</pre>
        <button className="button secondary" onClick={pinOutput} disabled={busy || !activeToken}>
          <Pin size={15}/>테스트 출력 고정</button>
      </>}
      {pin && <div className="node-lab-uploaded">
        <strong>기존 고정 출력: {pin.label}</strong>
        <pre className="node-lab-json small">{jsonString(pin.output)}</pre>
      </div>}
    </div>}
    {tab === 'history' && <div className="node-lab-content">
      <div className="node-lab-buttons">
        <button className="button secondary" onClick={refreshData} disabled={busy || !activeToken}>
          <History size={15}/>이력 조회</button>
      </div>
      {!history.length && <div className="node-lab-warning">저장된 테스트 기록이 없습니다.</div>}
      {history.map((entry) => <div className="node-lab-history" key={entry.id}>
        <span>#{entry.id} · {entry.mode} · {entry.status} · {entry.duration_ms}ms</span>
        <button className="button secondary" onClick={() => replay(entry)}><RotateCcw size={14}/>동일 입력 재현</button>
        <details><summary>실제 결과 보기</summary>
          <pre className="node-lab-json small">{jsonString(entry.result)}</pre></details>
      </div>)}
    </div>}
    {error && <div className="node-lab-error" role="alert"><AlertCircle size={15}/>{error}</div>}
  </section>;
}
