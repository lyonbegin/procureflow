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
        if urlsplit(self.path).path in (
           "/api/procurement/public9/action-result",
           "/api/procurement/public9/action-file",
        ):
            if WORKFLOW_DIR!="procure-workflows":
                return self._json(404,{"error":"PROCUREMENT_ONLY"})
            try:
                import github_actions_bridge as bridge
                length=int(self.headers.get("Content-Length","0"))
                path=urlsplit(self.path).path
                ceiling=bridge.MAX_UPLOAD_CHUNK if path.endswith("action-file") else 4000000
                if not 0<length<=ceiling:
                    raise ValueError("GITHUB_ACTION_CALLBACK_SIZE_INVALID")
                raw=self.rfile.read(length)
                auth=self.headers.get("Authorization","")
                result=(bridge.upload(auth,self.headers,raw)
                    if path.endswith("action-file") else
                    bridge.receive(auth,json.loads(raw)))
                return self._json(200,result)
            except (ValueError,TypeError,LookupError) as exc:
                return self._json(403,{"error":str(exc),"railway_crawl_fallback":False})
            except Exception as exc:
                return self._json(503,{"error":"GH_ACTION_CALLBACK_FAILED",
                    "detail":type(exc).__name__,"railway_crawl_fallback":False})
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
                import github_actions_bridge
                response=github_actions_bridge.begin(sid,body)
                return self._json(202,response,sid,new_cookie)
            except ValueError as exc:
                return self._json(409,{"error":str(exc),"bid_submitted":False},sid,new_cookie)
            except RuntimeError as exc:
                return self._json(503,{"error":str(exc),"bid_submitted":False},sid,new_cookie)
            except Exception as exc:
                return self._json(503,{"error":"GITHUB_ACTIONS_DISPATCH_UNAVAILABLE",
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
        if path in ("/api/procurement/public9/action-input",
                    "/api/procurement/public9/action-original"):
            if WORKFLOW_DIR!="procure-workflows":
                return self._json(404,{"error":"PROCUREMENT_ONLY"})
            try:
                import github_actions_bridge as bridge
                from urllib.parse import parse_qs
                q=parse_qs(urlsplit(self.path).query)
                rid=(q.get("run_id") or [""])[0]
                auth=self.headers.get("Authorization","")
                if path.endswith("action-input"):
                    return self._json(200,bridge.context(auth,rid,(q.get("stage") or [""])[0]))
                seq=int((q.get("file_seq") or ["0"])[0])
                source=bridge.original(auth,rid,seq)
                self.send_response(200)
                self.send_header("Content-Type","application/octet-stream")
                self.send_header("Content-Length",str(source.stat().st_size))
                self.send_header("Cache-Control","no-store")
                self.send_header("X-Content-Type-Options","nosniff")
                self.end_headers()
                with source.open("rb") as handle:
                    while (part:=handle.read(1024*1024)):
                        self.wfile.write(part)
                return
            except (ValueError,TypeError,LookupError) as exc:
                return self._json(403,{"error":str(exc)})
            except Exception as exc:
                return self._json(503,{"error":"GH_ACTION_INPUT_OR_FILE_FAILED",
                    "detail":type(exc).__name__})
        if path=="/api/procurement/public9/live-run":
            sid,new_cookie=self._sid()
            if WORKFLOW_DIR!="procure-workflows":
                return self._json(404,{"error":"PROCUREMENT_ONLY"},sid,new_cookie)
            import github_actions_bridge
            return self._json(200,github_actions_bridge.current(sid),sid,new_cookie)
        if path=="/api/procurement/public9/live-docx":
            sid,new_cookie=self._sid()
            from urllib.parse import parse_qs
            args=parse_qs(urlsplit(self.path).query)
            rid=(args.get("run_id") or [""])[0]
            if WORKFLOW_DIR!="procure-workflows" or not re.fullmatch(r"[a-f0-9]{32}",rid):
                return self._json(404,{"error":"INVALID_DOCUMENT_REQUEST"},sid,new_cookie)
            try:
                import github_actions_bridge
                raw=github_actions_bridge.document(sid,rid)
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
