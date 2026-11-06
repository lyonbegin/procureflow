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
        if urlsplit(self.path).path=="/api/procurement/public9/test":
            sid,cookie=self._sid()
            if WORKFLOW_DIR!="procure-workflows":
                return self._json(404,{"error":"PROJECT_ROUTE_NOT_AVAILABLE"},sid,cookie)
            origin=self.headers.get("Origin","")
            parsed=urlsplit(origin)
            if not origin or parsed.netloc!=self.headers.get("Host") or parsed.scheme not in ("https","http"):
                return self._json(403,{"error":"SAME_ORIGIN_TEST_ONLY"},sid,cookie)
            if not self.headers.get("Content-Type","").startswith("application/json"):
                return self._json(415,{"error":"JSON_REQUIRED"},sid,cookie)
            try:
                count=int(self.headers.get("Content-Length","0"))
                if count<2 or count>250:
                    raise ValueError("TEST_INPUT_SIZE_INVALID")
                body=json.loads(self.rfile.read(count))
                import procurement_auto_test
                result=procurement_auto_test.run(sid,DB_PATH,fixture_path,body)
                return self._json(200,result,sid,cookie)
            except (TypeError,ValueError,json.JSONDecodeError) as exc:
                return self._json(422,{"status":"BLOCKED","error":str(exc),
                    "worker_executed":False,"bid_submitted":False},sid,cookie)
            except Exception as exc:
                return self._json(503,{"status":"REAL_SOURCE_UNAVAILABLE",
                    "detail":type(exc).__name__,
                    "worker_executed":False,"bid_submitted":False},sid,cookie)
        if urlsplit(self.path).path=="/api/procurement/public9/prepare":'''
if src.count(old)!=1:raise RuntimeError("PINNED_SERVER_POST_ROUTING_MISMATCH")
path.write_text(src.replace(old,route))
print("PROCUREFLOW_TOKEN_FREE_READ_ONLY_TEST_ROUTE_INSTALLED")
