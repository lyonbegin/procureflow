"""Patch only the pinned local ProcureFlow Studio server copy.

Append no-token TEST-ONLY route. Keep existing signed operating Worker endpoint
unchanged. Browser cannot cause any side effect on procurement backend.
"""
from pathlib import Path
import sys
path=Path(sys.argv[1])
src=path.read_text()
old='''    def do_POST(self):
        if urlsplit(self.path).path=="/api/procurement/public9/prepare":'''
route='''    def do_POST(self):
        if urlsplit(self.path).path=="/api/procurement/public9/run-all":
            sid,new_cookie=self._sid()
            if WORKFLOW_DIR!="procure-workflows":
                return self._json(404,{"error":"PROCUREMENT_ONLY"},sid,new_cookie)
            if new_cookie:
                return self._json(403,{"error":"ESTABLISHED_STUDIO_SESSION_REQUIRED"},sid,new_cookie)
            origin=self.headers.get("Origin","")
            parsed=urlsplit(origin)
            if (not origin or parsed.netloc!=self.headers.get("Host")
                or parsed.scheme not in ("https","http")):
                return self._json(403,{"error":"SAME_ORIGIN_REQUIRED"},sid,new_cookie)
            if not self.headers.get("Content-Type","").startswith("application/json"):
                return self._json(415,{"error":"JSON_REQUIRED"},sid,new_cookie)
            try:
                count=int(self.headers.get("Content-Length","0"))
                if not 2<=count<=250:
                    raise ValueError("INVALID_RUN_ALL_BODY")
                body=json.loads(self.rfile.read(count))
                import live_nine_test
                response=live_nine_test.begin(sid,body)
                return self._json(202,response,sid,new_cookie)
            except ValueError as exc:
                return self._json(409,{"error":str(exc),"bid_submitted":False},sid,new_cookie)
            except RuntimeError as exc:
                return self._json(503,{"error":str(exc),"bid_submitted":False},sid,new_cookie)
            except Exception as exc:
                return self._json(503,{"error":"DIRECT_NINE_STAGE_UNAVAILABLE",
                    "detail":type(exc).__name__,"bid_submitted":False},sid,new_cookie)
        if urlsplit(self.path).path=="/api/procurement/public9/test":
            sid,cookie=self._sid()
            return self._json(410,{"error":"DATABASE_TEST_RETIRED_USE_OFFICIAL_LIVE_RUN_ALL",
                                   "db_reads":0,"worker_calls":0,"bid_submitted":False},sid,cookie)
        if urlsplit(self.path).path=="/api/procurement/public9/prepare":'''
if src.count(old)!=1:raise RuntimeError("PINNED_SERVER_POST_ROUTING_MISMATCH")
src=src.replace(old,route)
start=src.index('        if urlsplit(self.path).path=="/api/procurement/public9/prepare":')
end=src.index('        if urlsplit(self.path).path == "/api/investment/pipeline":',start)
src=src[:start]+'''        if urlsplit(self.path).path=="/api/procurement/public9/prepare":
            sid,cookie=self._sid()
            return self._json(410,{"error":"LEGACY_WORKER_QUEUE_REMOVED_USE_RUN_ALL",
                                   "bid_submitted":False},sid,cookie)
'''+src[end:]
# Pinned shared Studio GET supports same-origin cookie-scoped live run/status.
marker='''    def do_GET(self):
        path = urlsplit(self.path).path'''
if src.count(marker)!=1:
    raise RuntimeError("PINNED_SERVER_GET_ROUTE_MISMATCH")
new='''    def do_GET(self):
        path = urlsplit(self.path).path
        if path=="/api/procurement/public9/live-run":
            sid,new_cookie=self._sid()
            if WORKFLOW_DIR!="procure-workflows":
                return self._json(404,{"error":"PROCUREMENT_ONLY"},sid,new_cookie)
            import live_nine_test
            return self._json(200,live_nine_test.current(sid),sid,new_cookie)
        if path=="/api/procurement/public9/live-docx":
            sid,new_cookie=self._sid()
            from urllib.parse import parse_qs
            args=parse_qs(urlsplit(self.path).query)
            rid=(args.get("run_id") or [""])[0]
            if WORKFLOW_DIR!="procure-workflows" or not re.fullmatch(r"[a-f0-9]{32}",rid):
                return self._json(404,{"error":"INVALID_DOCUMENT_REQUEST"},sid,new_cookie)
            try:
                import live_nine_test
                raw=live_nine_test.document(sid,rid)
            except LookupError:
                return self._json(404,{"error":"DOCUMENT_NOT_AVAILABLE"},sid,new_cookie)
            return self._send(200,raw,
                  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                  sid,new_cookie,extra={"Cache-Control":"no-store",
                     "Content-Disposition":"attachment; filename=ProcureFlow-Live9-Test.docx"})
'''
src=src.replace(marker,new,1)
path.write_text(src)
print("PROCUREFLOW_ON_DEMAND_LIVE_NINE_NO_DATABASE_ROUTE_INSTALLED")
