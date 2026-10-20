"""Read-only discovery of G2B detail/notice XHR via an existing Chrome CDP session.

No HTTP requests are initiated. Credentials, cookies, request bodies and response
bodies are not persisted. Only endpoint paths and small nonsecret ID field samples
are exposed locally to help determine actual detail/notice endpoint schemas.
"""
from __future__ import annotations
import base64
import collections
import json
import re
import threading
from urllib.parse import urlsplit

G2B_HOST = 'www.g2b.go.kr'
LIST_PATH = '/pr/prc/prca/OderReq/selectOderReqList.do'
HINT = re.compile(r'(oder|pbanc|pblanc|bid|ntce|spec|prc)', re.I)
ORDER_KEYS = frozenset({'oderPlanNo', 'stepOderPlanNo', 'oderReqNo'})
BID_KEYS = frozenset({'bidNtceNo', 'bidPbancNo', 'bidPblancNo', 'bidNo', 'pbancNo', 'bidNoticeNo'})
MAX_PENDING = 120


def eligible(url: str, method: str = 'GET') -> bool:
    try:
        p = urlsplit(url)
        return (p.scheme == 'https' and p.hostname == G2B_HOST
                and p.path.startswith('/') and p.path.lower().endswith('.do')
                and p.path != LIST_PATH and HINT.search(p.path) is not None
                and method.upper() in ('GET', 'POST'))
    except (ValueError, AttributeError):
        return False


def id_samples(payload, limit=18):
    """Only explicit numeric/alphanumeric ID fields, never arbitrary text or tokens."""
    found, visited = [], 0
    stack = [payload]
    while stack and len(found) < limit and visited < 900:
        node = stack.pop()
        visited += 1
        if isinstance(node, dict):
            for k, v in node.items():
                if k in (ORDER_KEYS | BID_KEYS) and isinstance(v, (str, int)):
                    value = str(v).strip()
                    if 4 <= len(value) <= 48 and re.fullmatch(r'[A-Za-z0-9-]+', value):
                        pair = {'key': k, 'value': value}
                        if pair not in found:
                            found.append(pair)
            stack.extend(v for v in node.values() if isinstance(v, (list, dict)))
        elif isinstance(node, list):
            stack.extend(node[:250])
    return found


class XhrProbe:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending = {}
        self._history = collections.deque(maxlen=60)
        self._observed = 0

    def on_request(self, session, event):
        req = event.get('request') or {}
        if not eligible(req.get('url', ''), req.get('method', 'GET')):
            return
        rid = event.get('requestId')
        if not rid:
            return
        path = urlsplit(req['url']).path  # exclude query tokens
        with self._lock:
            if len(self._pending) >= MAX_PENDING:
                self._pending.pop(next(iter(self._pending)))
            self._pending[(id(session), rid)] = {'path': path, 'method': req.get('method', ''),
                                                  'status': None, 'xhr': False, 'json': False}

    def on_response(self, session, event):
        key = (id(session), event.get('requestId'))
        with self._lock:
            item = self._pending.get(key)
            if item is not None:
                res = event.get('response') or {}
                item['status'] = int(res.get('status') or 0)
                item['xhr'] = event.get('type') in ('XHR', 'Fetch')
                mime = res.get('mimeType', '') or ''
                headers = {str(k).lower(): str(v) for k, v in (res.get('headers') or {}).items()}
                item['json'] = 'json' in mime.lower() or 'json' in headers.get('content-type', '').lower()

    def on_finish(self, session, event):
        key = (id(session), event.get('requestId'))
        with self._lock:
            item = self._pending.pop(key, None)
        if not item or not item['xhr']:
            return
        entry = {'path': item['path'], 'method': item['method'], 'status': item['status'],
                 'json_keys': [], 'identifiers': [], 'response': 'HTTP '+str(item['status'])}
        if item['status'] == 200:
            try:
                data = session.send('Network.getResponseBody', {'requestId': event['requestId']})
                body = data.get('body') or ''
                if data.get('base64Encoded'):
                    body = base64.b64decode(body).decode('utf-8-sig')
                # Some G2B JSON endpoints use text/plain; parse by content, not MIME only.
                if not body.lstrip().startswith(('{','[')):
                    entry['response'] = 'JSON 아닌 응답'
                    raise ValueError('Not JSON')
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    entry['json_keys'] = list(parsed)[:16]
                entry['identifiers'] = id_samples(parsed)
                entry['response'] = 'JSON 응답'
            except Exception:
                if entry['response'] != 'JSON 아닌 응답':
                    entry['response'] = '본문 구조 분석 불가'
        with self._lock:
            self._history.appendleft(entry)
            self._observed += 1

    def on_failed(self, session, event):
        key = (id(session), event.get('requestId'))
        with self._lock:
            self._pending.pop(key, None)

    def snapshot(self):
        with self._lock:
            return {'observed': self._observed, 'recent': list(self._history)}
