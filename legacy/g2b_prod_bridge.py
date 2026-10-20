"""Capture actual G2B 조달요청 POST JSON in Chrome :9333, not visible DOM rows.

Capture only requests to a specified HTTPS same-origin endpoint. Session cookies
remain inside Chrome; this program never exports credentials or session cookies.
"""
from __future__ import annotations
import copy
import base64
import datetime as dt
import html
import json
import queue
import re
import threading
import g2b_prod_xhr_probe as xhr_probe
import g2b_prod_nav as g2b_autonav
import time
from urllib.parse import parse_qsl, urlencode, urlsplit
from pathlib import Path

DEFAULT_PAYLOAD = json.loads((Path(__file__).resolve().parent / "g2b_prod_payload.json").read_text(encoding="utf-8"))

CDP_URL = 'http://127.0.0.1:9333'
PATH = '/pr/prc/prca/OderReq/selectOderReqList.do'
DOMAIN = 'www.g2b.go.kr'
PAGE_KEYS = ('currentPage', 'pageIndex', 'pageNo', 'pageNum', 'page', 'current_page')
FORCED_PAGE_SIZE = 100
ALLOWED_CATEGORIES = ('01', '03')
CATEGORY_FILTER = '01 03'  # 물품, 일반용역 only


def is_target(url, method='POST'):
    try:
        p = urlsplit(url)
        return method.upper() == 'POST' and p.scheme == 'https' and p.hostname == DOMAIN and p.path == PATH
    except (ValueError, AttributeError):
        return False


def parse_json_response(payload):
    if isinstance(payload, bytes):
        payload = json.loads(payload.decode('utf-8-sig'))
    elif isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError('응답 루트는 JSON 객체여야 합니다.')
    if str(payload.get('ErrorCode')) not in ('0', '00'):
        raise ValueError('나라장터 반환 오류: ' + str(payload.get('ErrorMsg', payload.get('ErrorCode'))))
    records = payload.get('dlOderReqL')
    if not isinstance(records, list):
        raise ValueError('dlOderReqL 배열이 없습니다. 이 응답은 조달요청 목록이 아닙니다.')
    out = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        number = str(rec.get('oderPlanNo') or rec.get('unikey') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9-]{5,100}', number):
            continue
        out.append({
            'request_no': number,
            'title': html.unescape(str(rec.get('bizNm') or '')).strip(),
            'agency': html.unescape(str(rec.get('oderInstUntyGrpNm') or '')).strip(),
            'category': html.unescape(str(rec.get('prcmBsneSeNm') or '')).strip(),
            'category_code': str(rec.get('prcmBsneSeCd') or '').strip(),
            'budget': max(0, int(rec.get('bgtSumAmt') or 0)),
            'procurement': html.unescape(str(rec.get('prcmMthoSeNm') or '')).strip(),
            'contract': html.unescape(str(rec.get('stdCtrtMthdNm') or '')).strip(),
            'request_date': str(rec.get('prcsYmd') or ''),
            'order_month': str(rec.get('oderYymm') or ''),
            'bid_linked': str(rec.get('bidPbancRfrnYn') or 'N').upper() == 'Y',
            'spec_linked': str(rec.get('bfSpecRfrnYn') or 'N').upper() == 'Y',
            'raw_json': json.dumps(rec, ensure_ascii=False),
        })
    first = records[0] if records else {}
    return {
        'items': out,
        'total': int(first.get('totCnt') or len(out)),
        'page': int(first.get('currentPage') or 1),
        'page_size': int(first.get('recordCountPerPage') or len(out) or 100),
        'has_next': str(first.get('nextRowYn') or 'N').upper() == 'Y',
        'raw_count': len(records),
    }


def change_page(body, content_type, page):
    """Modify nested dlOderReqSrchM.currentPage; preserve *every* other filter."""
    if not isinstance(body, str) or not body:
        raise ValueError('POST 요청 본문이 비어 있습니다.')
    content_type = (content_type or '').lower()
    if 'application/json' in content_type or body.lstrip().startswith('{'):
        obj = json.loads(body)
        if not isinstance(obj, dict):
            raise ValueError('POST JSON 객체만 지원합니다.')
        section = obj.get('dlOderReqSrchM')
        if isinstance(section, dict) and 'currentPage' in section:
            old_value = section['currentPage']
            section['currentPage'] = str(page) if isinstance(old_value, str) else int(page)
            return json.dumps(obj, ensure_ascii=False, separators=(',', ':')), 'dlOderReqSrchM.currentPage'
        for k in PAGE_KEYS:
            if k in obj:
                obj[k] = str(page) if isinstance(obj[k], str) else int(page)
                return json.dumps(obj, ensure_ascii=False, separators=(',', ':')), k
        raise ValueError('POST JSON에 페이지 변수가 없습니다.')
    pairs = parse_qsl(body, keep_blank_values=True)
    keys = list(PAGE_KEYS) + ['dlOderReqSrchM.currentPage']
    for k in keys:
        if any(p == k for p, _ in pairs):
            return urlencode([(p, str(page) if p == k else v) for p, v in pairs]), k
    raise ValueError('POST Form Data에서 페이지 변수를 찾지 못했습니다.')



def normalize_search_filters(start_date=None, end_date=None, order_start=None,
                             order_end=None, biz_name=None):
    """Validate the manager's search fields; all other source XHR fields remain intact."""
    defaults = DEFAULT_PAYLOAD['dlOderReqSrchM']
    def to_ymd(value, key, fallback):
        s = str(value if value not in (None, '') else fallback).replace('-', '')
        if not re.fullmatch(r'\d{8}', s):
            raise ValueError(f'{key}: YYYYMMDD 형식이어야 합니다.')
        dt.datetime.strptime(s, '%Y%m%d')
        return s
    def to_ym(value, key, fallback):
        s = str(value if value not in (None, '') else fallback).replace('-', '')
        if not re.fullmatch(r'\d{6}', s):
            raise ValueError(f'{key}: YYYYMM 형식이어야 합니다.')
        dt.datetime.strptime(s, '%Y%m')
        return s
    begin = to_ymd(start_date, '진행 시작일', defaults['prgrsBgngYmd'])
    finish = to_ymd(end_date, '진행 종료일', defaults['prgrsEndYmd'])
    order_begin = to_ym(order_start, '발주 시작월', defaults['oderStYm'])
    order_finish = to_ym(order_end, '발주 종료월', defaults['oderEdYm'])
    if begin > finish:
        raise ValueError('진행 시작일은 종료일 이후일 수 없습니다.')
    if order_begin > order_finish:
        raise ValueError('발주 시작월은 종료월 이후일 수 없습니다.')
    name = str(biz_name if biz_name is not None else defaults.get('bizNm', '')).strip()
    if len(name) > 200:
        raise ValueError('사업명은 200자 이내여야 합니다.')
    return {'srchTy':'0001', 'prcmBsneSeCd':CATEGORY_FILTER,
            'prgrsBgngYmd':begin, 'prgrsEndYmd':finish,
            'oderStYm':order_begin, 'oderEdYm':order_finish, 'bizNm':name}


def change_page_and_size(body, content_type, page, page_size=FORCED_PAGE_SIZE, filters=None):
    """Preserve browser XHR and set page, 100 rows, and selected search filters."""
    edited, key = change_page(body, content_type, page)
    if not edited.lstrip().startswith('{'):
        raise ValueError('원본 나라장터 XHR JSON 요청만 지원합니다.')
    obj = json.loads(edited)
    model = obj.get('dlOderReqSrchM')
    if not isinstance(model, dict):
        raise ValueError('dlOderReqSrchM 검색 모델이 없습니다.')
    model['recordCountPerPage'] = str(FORCED_PAGE_SIZE)
    model['prcmBsneSeCd'] = CATEGORY_FILTER
    if filters:
        allowed = {'srchTy','prcmBsneSeCd','prgrsBgngYmd','prgrsEndYmd',
                   'oderStYm','oderEdYm','bizNm'}
        model.update({k:v for k,v in filters.items() if k in allowed})
        # UI cannot override these two fixed rules.
        model['prcmBsneSeCd'] = CATEGORY_FILTER
        model['recordCountPerPage'] = str(FORCED_PAGE_SIZE)
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')), key


def payload_with_dates(start_date=None, end_date=None):
    payload = copy.deepcopy(DEFAULT_PAYLOAD)
    section = payload['dlOderReqSrchM']
    for key, value in [('prgrsBgngYmd', start_date), ('prgrsEndYmd', end_date)]:
        if value is not None:
            value = str(value).replace('-', '')
            if not re.fullmatch(r'\d{8}', value):
                raise ValueError(f'{key}는 YYYYMMDD 형식이어야 합니다.')
            # Calendar validation catches dates such as 20260230.
            dt.datetime.strptime(value, '%Y%m%d')
            section[key] = value
    if section['prgrsBgngYmd'] > section['prgrsEndYmd']:
        raise ValueError('조회 시작일은 종료일보다 이후일 수 없습니다.')
    return payload


class Monitor:
    def __init__(self, save_callback):
        self.save_callback = save_callback
        self._thread = None
        self._stop = threading.Event()
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._state = dict(running=False, connected=False, message='대기 중', captured_responses=0,
                           last_saved=0, total=None, page=None, page_size=None, last_seen=None,
                           batch_active=False, batch_done=0, batch_goal=0, batch_added=0, batch_updated=0, batch_skipped=0, batch_filtered=0,
                           failed_pages=[], requested=None, page_limit=None, batch_complete=False, queued=False, xhr_hooked_tabs=0, xhr_ready=False, last_capture_page_size=None, last_capture_url=None)
        self._last_request = None
        self._frame = None
        self._suppressed = False
        self._cancel_batch = threading.Event()
        self._cdp_pending = {}
        self._cdp_completed = queue.Queue()
        self._attached_sessions = {}
        self._original_cdp = None   # The original real 200-OK XHR, including CDP Network requestId.
        self._native_page = None
        self._native_hook_session = None
        self._native_expected = None
        self._native_results = queue.Queue()
        self._native_seen_request = set()
        self._native_intercepted = False
        self._active_filters = None
        self._auto_collect_on_hook = False  # legacy; pending collection owns the job
        self._pending_collect = None
        self._nav_queued = False
        self._route_cache = Path(__file__).resolve().parent / 'g2b_search_route.json'
        self.probe = xhr_probe.XhrProbe()

    def status(self):
        with self._lock:
            return dict(self._state)

    def _update(self, **changes):
        with self._lock:
            self._state.update(changes)

    def start(self):
        if self._thread and self._thread.is_alive():
            return self.status()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name='G2B-POST-JSON-Watcher')
        self._thread.start()
        self._update(running=True, message='Headless Chrome 직접 실행 및 나라장터 발주목록 자동 진입 준비 중')
        return self.status()

    def _queue_auto_navigation(self):
        """Queue only one navigation operation, including during CDP reconnect."""
        with self._lock:
            if self._nav_queued:
                return False
            self._nav_queued = True
            self._state['auto_navigation'] = {'ok': None, 'stage': 'queued'}
            self._state['message'] = '발주 → 발주목록 → 검색 자동 실행 대기 중'
        self._queue.put({'mode': 'auto_nav'})
        return True

    def auto_start(self, collect=True):
        """Start CDP monitoring/navigation without ever asking for a manual click."""
        if collect:
            with self._lock:
                if self._pending_collect is None:
                    self._pending_collect = {'count': 10000, 'filters': None}
        if self._last_request and self.status().get('xhr_ready'):
            with self._lock:
                pending = self._pending_collect
                self._pending_collect = None
            if pending:
                self._queue.put({'mode': 'xhr_replay', **pending})
                self._update(queued=True, message='포착된 검색 XHR로 자동 수집 예약')
                return {'queued': True, 'message': '검색 XHR이 준비되어 자동 수집을 예약했습니다.'}
            return {'queued': False, 'message': '이미 검색 XHR이 준비되어 있습니다.'}
        self.start()
        self._queue_auto_navigation()
        return {'queued': True, 'message': '발주 → 발주목록 → 검색을 자동 실행하고, XHR을 확보하면 수집합니다.'}

    def stop(self):
        """Cancel the current batch without disconnecting from Chrome."""
        self._cancel_batch.set()
        with self._lock:
            self._pending_collect = None
        return self.status()

    def pages(self, num):
        if not self.status().get('running') or not self.status().get('connected') or not self._last_request:
            return self.collect(page_limit=num)
        num = int(num)
        if num < 1 or num > 250:
            raise ValueError('추가 수집 페이지는 1~250 사이여야 합니다.')
        self._queue.put({'mode':'captured','count':num})
        return {'queued': True, 'pages': num, 'message': '추가 페이지 수집이 예약되었습니다. 진행상황을 확인해 주십시오.'}

    def collect(self, page_limit=3000, start_date=None, end_date=None,
                order_start=None, order_end=None, biz_name=None):
        """Collect immediately when ready, otherwise automatically open and search.

        User options survive the navigation, CDP hook and XHR capture. The
        request is NOT sent from Python: we replay the browser's actual POST.
        """
        count = int(page_limit)
        if not 1 <= count <= 10000:
            raise ValueError('수집 한도는 1~10000페이지 사이로 지정해 주십시오.')
        filters = normalize_search_filters(start_date, end_date, order_start, order_end, biz_name)
        if self.status().get('batch_active'):
            raise ValueError('이미 수집 중입니다.')
        task = {'count': count, 'filters': filters}
        if self._last_request and self.status().get('xhr_ready'):
            if self.status().get('queued'):
                raise ValueError('이미 수집이 예약되어 있습니다.')
            if self._frame is None or self._frame.is_detached():
                self._last_request = None
                self._update(xhr_ready=False)
            else:
                self._cancel_batch.clear()
                self._update(queued=True, requested=count, batch_complete=False,
                             message='포착된 Chrome XHR 원본으로 100건/페이지 수집 예약')
                self._queue.put({'mode':'xhr_replay', **task})
                return {'queued':True,'pages':count,
                        'message':'100건씩 수집을 예약했습니다.'}
        # New session / not yet captured: no manual browser interaction required.
        with self._lock:
            self._pending_collect = task
            self._state['requested'] = count
            self._state['batch_complete'] = False
        self._cancel_batch.clear()
        self.start()
        self._queue_auto_navigation()
        return {'queued':True,'pages':count,'waiting_for_xhr':True,
                'message':'발주 → 발주목록 → 검색을 자동 실행합니다. XHR 포착 즉시 설정한 조건으로 수집합니다.'}

    def _get_g2b_frame(self, browser):
        if self._frame is not None:
            try:
                if not self._frame.is_detached() and urlsplit(self._frame.url).hostname == DOMAIN:
                    return self._frame
            except Exception:
                pass
        for context in browser.contexts:
            for page in context.pages:
                for frame in page.frames:
                    try:
                        addr = urlsplit(frame.url)
                        if addr.scheme == 'https' and addr.hostname == DOMAIN:
                            return frame
                    except Exception:
                        continue
        raise ValueError('Chrome 9333에 열린 나라장터 탭이 없습니다. 전용 Chrome에서 https://www.g2b.go.kr/ 를 열어주십시오.')

    def _fetch_paused(self, session, event):
        """Modify only the POST payload of the ORIGINAL browser XHR replay.

        Replay inherits the original AJAX request headers, CSRF handling,
        credentials and page context. Unlike a new XMLHttpRequest, it is the
        same request as the successful user-originated search.
        """
        request_id = event['requestId']
        req = event.get('request') or {}
        override = {}
        try:
            if (self._native_expected is not None and
                session is self._original_cdp['session'] and
                is_target(req.get('url', ''), req.get('method', ''))):
                original_body = req.get('postData') or self._last_request['body']
                edited, _ = change_page_and_size(
                    original_body, self._last_request['content_type'], self._native_expected,
                    filters=self._active_filters)
                override['postData'] = base64.b64encode(edited.encode('utf-8')).decode('ascii')
                network_id = event.get('networkId')
                if network_id:
                    self._native_seen_request.add(network_id)
                self._native_intercepted = True
            # Crucially: do not override headers. Chrome preserves original
            # browser request headers, tokens, referrer and cookies.
        except Exception as exc:
            self._native_results.put({'error':'페이지 요청 변경 실패: '+str(exc)})
        finally:
            session.send('Fetch.continueRequest', {'requestId': request_id, **override})

    def _native_replay(self, browser, page_no):
        original = self._original_cdp
        if not original or not original.get('request_id'):
            raise ValueError('원본 XHR이 만료되었습니다. 발주목록 자동 검색을 다시 실행하십시오.')
        session = original['session']
        self._native_expected = page_no
        self._native_intercepted = False
        self._native_seen_request.clear()
        while not self._native_results.empty():
            try: self._native_results.get_nowait()
            except queue.Empty: break
        try:
            # CDP native request replay retains the browser's original XHR
            # semantics; interception changes only page and page size.
            session.send('Network.replayXHR', {'requestId': original['request_id']})
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                if self._cancel_batch.is_set() or self._stop.is_set():
                    raise ValueError('사용자가 수집을 중지했습니다.')
                self._process_cdp_completed()
                try:
                    item = self._native_results.get_nowait()
                except queue.Empty:
                    # Wait via Playwright to dispatch CDP event handlers.
                    original['page'].wait_for_timeout(140)
                    continue
                if 'error' in item:
                    raise ValueError(str(item['error']))
                if not self._native_intercepted:
                    raise ValueError('Chrome 네트워크 XHR 수정이 적용되지 않았습니다.')
                return item['response']
            raise ValueError(f'Chrome 원본 XHR 재실행 {page_no}페이지 응답 대기 35초 초과')
        finally:
            self._native_expected = None

    def _same_origin_xhr(self, page_no):
        """Fallback: use a true XMLHttpRequest inside the already-open G2B Chrome.

        This is *not* a Python requests session. Cookies and origin remain in Chrome;
        only safe headers from the observed working POST are forwarded. Never log
        private token values. The browser may refuse some website-specific cases.
        """
        if not self._last_request:
            raise ValueError('원본 나라장터 검색 XHR이 없습니다.')
        frame=self._frame
        if frame is None or frame.is_detached():
            raise ValueError('나라장터 검색 화면 프레임이 없습니다.')
        text, _ = change_page_and_size(self._last_request['body'],
                      self._last_request['content_type'],page_no,filters=self._active_filters)
        url=self._last_request['url']
        hdrs=self._last_request.get('headers',{})
        outcome=frame.evaluate(r'''async ({url,payload,headers}) => {
          return await new Promise(resolve => {
            const xhr=new XMLHttpRequest();
            xhr.open('POST',url,true);
            xhr.withCredentials=true;
            xhr.timeout=30000;
            for(const [k,v] of Object.entries(headers)){
              if(!/^(content-type|accept|menu-info|submissionid|usr-id|target-id|x-csrf-token|x-xsrf-token|x-requested-with)$/i.test(k))continue;
              try{xhr.setRequestHeader(k,String(v));}catch(e){}
            }
            xhr.onload=()=>resolve({status:xhr.status,body:xhr.responseText});
            xhr.onerror=()=>resolve({status:0,error:'XMLHttpRequest network failure'});
            xhr.ontimeout=()=>resolve({status:0,error:'XMLHttpRequest 30s timeout'});
            xhr.send(payload);
          });
        }''', {'url':url,'payload':text,'headers':hdrs})
        if outcome.get('status')!=200:
            raise ValueError('브라우저 내부 XHR 상태: '+str(outcome.get('status'))+' '+str(outcome.get('error','')))
        try:return json.loads(outcome['body'])
        except Exception as exc:raise ValueError('브라우저 내부 XHR이 JSON이 아닙니다.') from exc

    def _perform_direct(self, browser, job):
        """Use Network.replayXHR + Fetch.continueRequest; no synthetic HTTP/XHR."""
        if not self._original_cdp or not self._last_request:
            raise ValueError('검색 XHR 연결이 끊겼습니다. 자동 검색을 다시 실행하십시오.')
        session = self._original_cdp['session']
        url = self._last_request['url']
        if not is_target(url):
            raise ValueError('후킹된 XHR 주소가 다릅니다.')
        goal = int(job['count'])
        self._active_filters = job.get('filters') or {'prcmBsneSeCd':CATEGORY_FILTER}
        self._update(batch_active=True, batch_done=0, batch_goal=goal,
                     batch_added=0, batch_updated=0, batch_skipped=0, batch_filtered=0, failed_pages=[], page_limit=goal,
                     batch_complete=False, message='원본 Chrome XHR 재실행으로 100건씩 수집 시작')
        total, added, updated, skipped, filtered = None, 0, 0, 0, 0
        failed, complete = [], False
        self._suppressed = True
        try:
            if session is not self._native_hook_session:
                session.on('Fetch.requestPaused', lambda event: self._fetch_paused(session,event))
                self._native_hook_session = session
            self._native_page = self._original_cdp['page']
            session.send('Fetch.enable', {'patterns':[{'urlPattern':urlsplit(url).scheme+'://'+urlsplit(url).netloc+urlsplit(url).path+'*', 'requestStage':'Request'}]})
            for page_number in range(1,goal+1):
                if self._stop.is_set() or self._cancel_batch.is_set(): break
                if total is not None and page_number > (total + FORCED_PAGE_SIZE - 1) // FORCED_PAGE_SIZE:
                    break
                parsed, problem = None, None
                for attempt in range(2):
                    try:
                        try:
                            payload = self._native_replay(browser, page_number)
                        except Exception as native_exc:
                            # Some Chrome builds no longer replay finished XHRs.
                            # Still use Chrome's own same-origin authenticated XHR.
                            try:
                                payload = self._same_origin_xhr(page_number)
                            except Exception as fallback_exc:
                                raise ValueError(f'원본 XHR 재실행: {native_exc}; 브라우저 내부 XHR: {fallback_exc}') from fallback_exc
                        parsed = parse_json_response(payload)
                        if parsed['page'] != page_number:
                            raise ValueError(f'요청 {page_number}페이지와 응답 {parsed["page"]}페이지가 다릅니다.')
                        if parsed['page_size'] != FORCED_PAGE_SIZE:
                            raise ValueError(f'100건 요청했지만 서버는 {parsed["page_size"]}건으로 응답했습니다.')
                        if total is None:
                            total=parsed['total']
                            expected=(total+FORCED_PAGE_SIZE-1)//FORCED_PAGE_SIZE if total else 1
                            self._update(total=total,page_size=FORCED_PAGE_SIZE,batch_goal=min(goal,expected))
                        if parsed['raw_count']==0 and total and page_number <= (total-1)//FORCED_PAGE_SIZE:
                            raise ValueError('데이터가 있는 페이지에서 0건을 반환했습니다.')
                        problem=None
                        break
                    except Exception as exc:
                        problem=str(exc)
                        if attempt == 0 and not self._cancel_batch.is_set():
                            time.sleep(1.2)
                if problem:
                    failed.append({'page':page_number,'error':problem[:240]})
                    self._update(batch_done=page_number,failed_pages=failed[:],
                                 message=f'{page_number}페이지 2회 실패: {problem[:180]}')
                    if total is None: break
                    continue
                stats=self.save_callback(parsed,'Chrome 원본 XHR 재실행 (100건)')
                added+=stats.get('added',0)
                updated+=stats.get('updated',0)
                skipped+=stats.get('skipped',0)
                filtered+=stats.get('filtered',0)
                self._update(page=page_number,captured_responses=self.status()['captured_responses']+1,
                             batch_done=page_number,batch_added=added,batch_updated=updated,
                             batch_skipped=skipped,batch_filtered=filtered,
                             last_saved=parsed['raw_count'],last_seen=dt.datetime.now().isoformat(timespec='seconds'),
                             message=f'{page_number}페이지 완료 / 신규 {added:,}건 / 중복 건너뜀 {skipped:,}건 / 대상외 {filtered:,}건')
                if not parsed['has_next'] or page_number*FORCED_PAGE_SIZE >= parsed['total']:
                    complete=True
                    break
                time.sleep(1.2)
            self._update(batch_active=False,batch_complete=complete and not failed,
                         failed_pages=failed[:],batch_added=added,batch_updated=updated,
                         batch_skipped=skipped,batch_filtered=filtered,
                         message=f'수집 종료: 신규 {added:,}건, 중복 건너뜀 {skipped:,}건, 대상외 {filtered:,}건, 실패 페이지 {len(failed)}개'+
                                 (f' (예: {failed[0]["page"]}페이지)' if failed else ''))
        finally:
            try: session.send('Fetch.disable')
            except Exception: pass
            self._native_expected=None
            self._active_filters=None
            self._suppressed=False
            self._update(batch_active=False,queued=False)

    def _attach_page(self, page, attached):
        """CDP Network hook: request POST payload + completed XHR response JSON."""
        if id(page) in attached or page.is_closed():
            return
        try:
            session = page.context.new_cdp_session(page)
            session.send('Network.enable')
            session.on('Network.requestWillBeSent', lambda ev: self._cdp_request(session, page, ev))
            session.on('Network.responseReceived', lambda ev: self._cdp_response(session, ev))
            session.on('Network.loadingFinished', lambda ev: self._cdp_finish(session, ev))
            session.on('Network.loadingFailed', lambda ev: self._cdp_fail(session, ev))
            attached.add(id(page))
            self._attached_sessions[id(page)] = session
            self._update(xhr_hooked_tabs=len(attached))
        except Exception as exc:
            self._update(message='Chrome XHR 후킹 연결 오류: ' + str(exc)[:200])

    def _cdp_request(self, session, page, event):
        self.probe.on_request(session, event)
        request = event.get('request') or {}
        url, method = request.get('url',''), request.get('method','')
        if not is_target(url, method):
            return
        request_id = event.get('requestId')
        headers = {str(k).lower():v for k,v in (request.get('headers') or {}).items()}
        self._cdp_pending[(id(session), request_id)] = {
            'session':session, 'page':page, 'url':url, 'body':request.get('postData'),
            'headers':headers, 'frame_id':event.get('frameId'), 'status':None, 'type':None,
        }

    def _cdp_response(self, session, event):
        self.probe.on_response(session, event)
        item = self._cdp_pending.get((id(session),event.get('requestId')))
        if not item:
            return
        response = event.get('response') or {}
        item['status'] = response.get('status')
        item['type'] = event.get('type')

    def _cdp_finish(self, session, event):
        self.probe.on_finish(session, event)
        key = (id(session),event.get('requestId'))
        item = self._cdp_pending.pop(key, None)
        if item and self._suppressed and self._native_expected is not None:
            if (not self._native_seen_request or event.get('requestId') in self._native_seen_request):
                if item.get('status') == 200:
                    self._cdp_completed.put((session,event.get('requestId'),item))
                else:
                    self._native_results.put({'error':'조달요청 XHR HTTP 오류: '+str(item.get('status'))})
            return
        if item and item.get('status') == 200 and item.get('type') in ('XHR','Fetch'):
            self._cdp_completed.put((session,event.get('requestId'),item))
        elif item:
            self._update(message='조달요청 XHR HTTP 오류: '+str(item.get('status')))

    def _cdp_fail(self, session, event):
        self.probe.on_failed(session, event)
        item = self._cdp_pending.pop((id(session),event.get('requestId')), None)
        if item and not event.get('canceled'):
            self._update(message='나라장터 POST XHR 실패: '+str(event.get('errorText',''))[:120])

    def _process_cdp_completed(self):
        """Drain after the Playwright event pump; getResponseBody is then safe."""
        while True:
            try:
                session, request_id, item = self._cdp_completed.get_nowait()
            except queue.Empty:
                return
            if self._suppressed:
                try:
                    body_data = session.send('Network.getResponseBody',{'requestId':request_id})
                    raw=body_data['body']
                    if body_data.get('base64Encoded'):
                        raw=base64.b64decode(raw).decode('utf-8-sig')
                    self._native_results.put({'response':json.loads(raw)})
                except Exception as exc:
                    self._native_results.put({'error':'Chrome XHR 응답 읽기 실패: '+str(exc)})
                continue
            try:
                body_data = session.send('Network.getResponseBody', {'requestId':request_id})
                raw = body_data['body']
                if body_data.get('base64Encoded'):
                    raw = base64.b64decode(raw)
                payload = json.loads(raw)
                parsed = parse_json_response(payload)
                # If Chrome omitted postData from requestWillBeSent, request it
                # using CDP before persisting search parameters.
                post_body = item.get('body')
                if not post_body:
                    try:
                        post_body = session.send('Network.getRequestPostData',{'requestId':request_id})['postData']
                    except Exception:
                        pass
                if not post_body:
                    raise ValueError('XHR 응답은 받았으나 원본 POST 페이로드를 읽지 못했습니다.')
                content_type = item['headers'].get('content-type','application/json;charset=UTF-8')
                page = item['page']
                frame = None
                for candidate in page.frames:
                    try:
                        if urlsplit(candidate.url).hostname == DOMAIN:
                            frame = candidate
                            break
                    except Exception: pass
                if frame is None:
                    raise ValueError('나라장터의 동일 출처 프레임을 찾을 수 없습니다.')
                self._frame = frame
                # Optional route caching must not invalidate a real HTTP-200
                # G2B XHR response. The URL may be '/' or the cache may be
                # unwritable; neither case affects collection.
                try:
                    g2b_autonav.remember(self._route_cache, frame.url)
                except (OSError, ValueError, AttributeError) as exc:
                    self._update(route_cache_warning=type(exc).__name__)
                self._original_cdp = {'session':session,'request_id':request_id,'page':page}
                self._last_request = {
                    'url':item['url'], 'body':post_body, 'content_type':content_type,
                    'headers':{k:v for k,v in item['headers'].items()
                               if k in ('x-csrf-token','x-xsrf-token','x-requested-with',
                                        'content-type','accept','menu-info','submissionid',
                                        'usr-id','target-id')},
                }
                stats = self.save_callback(parsed,'Chrome CDP XHR 응답 자동후킹')
                self._update(xhr_ready=True, last_capture_page_size=parsed['page_size'],
                             last_capture_url=item['url'],
                             message=f'XHR 후킹 성공: {parsed["page"]}페이지, {parsed["raw_count"]}건, '
                                     f'신규 {stats["added"]}건, 전체 {parsed["total"]:,}건',
                             captured_responses=self.status()['captured_responses']+1,
                             last_saved=parsed['raw_count'], total=parsed['total'], page=parsed['page'],
                             page_size=parsed['page_size'],
                             last_seen=dt.datetime.now().isoformat(timespec='seconds'))
                # Schedule the exact collection request that the user already
                # submitted. Do not require a second click after first XHR.
                with self._lock:
                    pending = self._pending_collect
                    self._pending_collect = None
                if pending and not self.status().get('batch_active'):
                    self._cancel_batch.clear()
                    self._queue.put({'mode': 'xhr_replay', **pending})
                    self._update(queued=True, message='검색 XHR 자동 포착 완료. 요청하신 조건으로 전체 수집 시작',
                                 requested=pending['count'])
            except Exception as exc:
                self._update(message='XHR 후킹 응답 처리 오류: '+str(exc)[:240])

    def _perform_pages(self, browser, count):
        """The next-pages button uses the identical native XHR replay path."""
        if not self._last_request or not self._original_cdp:
            raise ValueError('먼저 실제 나라장터 POST XHR을 후킹하십시오.')
        self._perform_direct(browser, {'count':int(count)})

    def _run(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self._update(running=False, message='Playwright가 없습니다: python -m pip install playwright')
            return
        while not self._stop.is_set():
            try:
                with sync_playwright() as pw:
                    import os
                    import shutil
                    profile_dir = Path(os.getenv('G2B_HEADLESS_PROFILE', str(Path(__file__).resolve().parent / 'g2b_headless_profile'))).resolve()
                    profile_dir.mkdir(parents=True, exist_ok=True)
                    show = os.getenv('G2B_SHOW_BROWSER', '0').lower() in ('1','true','yes','on')
                    opts = dict(user_data_dir=str(profile_dir), headless=not show,
                                accept_downloads=False, locale='ko-KR',
                                viewport={'width':1450,'height':950},
                                timezone_id='Asia/Seoul',
                                args=['--no-first-run','--no-default-browser-check'])
                    try:
                        context = pw.chromium.launch_persistent_context(channel='chrome', **opts)
                    except Exception as chrome_error:
                        exe = shutil.which('chromium') or shutil.which('chromium-browser')
                        if not exe:
                            raise RuntimeError('Google Chrome 실행 실패: ' + str(chrome_error)) from chrome_error
                        context = pw.chromium.launch_persistent_context(executable_path=exe, **opts)
                    class BrowserAdapter:
                        contexts = [context]
                        def close(self):
                            context.close()
                    browser = BrowserAdapter()
                    self._update(connected=True, message=('화면 표시 Chrome' if show else 'Headless Chrome') + ' 자동 실행 성공. 나라장터 검색 준비 중')
                    attached = set()
                    while not self._stop.is_set():
                        for context in browser.contexts:
                            for page in context.pages:
                                try:
                                    self._attach_page(page, attached)
                                except Exception: pass
                        try:
                            task = self._queue.get_nowait()
                        except queue.Empty:
                            task = None
                        if task is not None:
                            self._update(queued=False)
                            try:
                                if isinstance(task, dict) and task.get('mode') == 'auto_nav':
                                    result = None
                                    try:
                                        for attempt in range(2):
                                            result = g2b_autonav.auto_open_and_search(
                                                browser, self._route_cache, self._attach_page, attached)
                                            # WebSquare sometimes sends the real list POST even
                                            # though its search form is not recognized by the DOM
                                            # heuristic. A validated XHR beats UI-form guessing.
                                            self._process_cdp_completed()
                                            if self.status().get('xhr_ready'):
                                                result = {'ok': True, 'stage': 'xhr_captured',
                                                          'mode': 'observed_post',
                                                          'message': '실제 나라장터 검색 POST JSON 확인. 전체 수집으로 진행'}
                                                self._update(message=result['message'], auto_navigation=result)
                                                break
                                            self._update(message=result['message'], auto_navigation=result)
                                            if result['ok']:
                                                # A click is not proof that the G2B POST was seen.
                                                # Wait for the original site XHR and verify the
                                                # actual response was saved before calling it a success.
                                                deadline = time.monotonic() + 7
                                                while time.monotonic() < deadline and not self.status().get('xhr_ready'):
                                                    self._process_cdp_completed()
                                                    if self.status().get('xhr_ready'):
                                                        break
                                                    try:
                                                        result_page = next((p for c in browser.contexts for p in c.pages if not p.is_closed()), None)
                                                        if result_page:
                                                            result_page.wait_for_timeout(250)
                                                        else:
                                                            time.sleep(.25)
                                                    except Exception:
                                                        time.sleep(.25)
                                                self._process_cdp_completed()
                                                if self.status().get('xhr_ready'):
                                                    result['stage'] = 'xhr_captured'
                                                    result['message'] = '발주목록 자동 검색 및 실제 POST XHR 포착 완료'
                                                    self._update(auto_navigation=result)
                                                    break
                                                result = {**result, 'ok': False, 'stage': 'xhr_not_captured',
                                                          'message': '검색 버튼은 자동 클릭했지만 실제 POST XHR이 7초 내 포착되지 않았습니다.'}
                                            if attempt == 0:
                                                self._update(message='자동 재시도 (2회 중 1회 실패): ' + result['message'])
                                                time.sleep(1)
                                        if not self.status().get('xhr_ready'):
                                            self._update(message=result['message'] + ' 네트워크·화면 상태를 점검하십시오.',
                                                         auto_navigation=result)
                                    finally:
                                        with self._lock:
                                            self._nav_queued = False
                                elif isinstance(task, dict) and task.get('mode') == 'xhr_replay':
                                    self._perform_direct(browser,task)
                                elif isinstance(task, dict) and task.get('mode') == 'direct':
                                    self._perform_direct(browser,task)
                                else:
                                    self._perform_pages(browser,task['count'] if isinstance(task,dict) else task)
                            except Exception as exc:
                                self._update(batch_active=False, message='추가 페이지 수집 오류: '+str(exc))
                        self._process_cdp_completed()
                        # Event loop pumping is necessary for Python Playwright callbacks.
                        try:
                            if browser.contexts and browser.contexts[0].pages:
                                browser.contexts[0].pages[0].wait_for_timeout(450)
                            else: time.sleep(0.45)
                        except Exception: time.sleep(0.45)
                        self._process_cdp_completed()
                    try: browser.close()
                    except Exception: pass
            except Exception as exc:
                self._update(connected=False, message='Headless Chrome 재실행 대기: ' + str(exc)[:180])
                self._stop.wait(4)
        self._update(running=False, connected=False, batch_active=False, message='감시 중지')
