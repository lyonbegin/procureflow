"""Public read-only Railway smoke tests after n8n-only API migration.

DOES NOT prove n8n Main/Worker deployed or 10 live n8n executions.
It proves n8n native JSON/QA API available and obsolete React Flow paths gone.
"""
from __future__ import annotations
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = os.getenv("PROCUREFLOW_PUBLIC_URL",
                  "https://procureflow-api-production.up.railway.app").rstrip("/")
CHECKS = [
    ("/", "n8n-launcher"),
    ("/flow", "retired-flow-launcher"),
    ("/health", "health"),
    ("/openapi.json", "n8n-only-api"),
    ("/api/n8n/scenarios", "n8n-10-catalog"),
    ("/api/n8n/qa", "n8n-10-simulated-qa"),
    ("/api/g2b/cases/R26BK01787028/features", "104-api"),
]


def check(path: str, kind: str) -> dict:
    try:
        request = Request(BASE + path, headers={
            "User-Agent":"ProcureFlow-n8n-readonly-smoke/1.0",
            "Accept":"text/html,application/json",
        })
        with urlopen(request, timeout=18) as response:
            status = response.status
            body = response.read(3_000_000).decode("utf-8", errors="replace")
        ok = False
        if kind in ("n8n-launcher", "retired-flow-launcher"):
            ok = "n8n 단일 워크플로 플랫폼" in body and "10개 운영 시나리오" in body
            ok &= "/studio/assets/" not in body
        elif kind == "health":
            ok = json.loads(body).get("status") == "ok"
        elif kind == "n8n-only-api":
            paths = json.loads(body).get("paths",{})
            required = [
              "/api/n8n/scenarios",
              "/api/n8n/scenarios/{scenario_id}/verify",
              "/api/n8n/qa",
              "/api/g2b/cases/{bid_no}/features",
            ]
            old = ["/api/g2b/cases/{bid_no}/workflow/designs",
                   "/api/g2b/cases/{bid_no}/workflow/advance"]
            ok = all(path in paths for path in required) and all(path not in paths for path in old)
        elif kind == "n8n-10-catalog":
            doc=json.loads(body)
            ok = doc.get("total")==10 and len(doc.get("items",[]))==10
        elif kind == "n8n-10-simulated-qa":
            doc=json.loads(body)
            ok = (doc.get("total")==10 and doc.get("passed")==10
                  and doc.get("all_passed") is True
                  and doc.get("actual_n8n_runs_verified") is False)
        elif kind == "104-api":
            doc=json.loads(body)
            ok = doc.get("total")==104 and len(doc.get("features",[]))==104
        return {"path":path, "http_status":status,"ok":bool(ok),"kind":kind,
                "explanation":"ok" if ok else "unexpected response or old deployment"}
    except HTTPError as exc:
        return {"path":path,"ok":False,"http_status":exc.code,"error":"HTTPError"}
    except (URLError,TimeoutError,OSError,ValueError,json.JSONDecodeError) as exc:
        return {"path":path,"ok":False,"error":type(exc).__name__+": "+str(exc)[:160]}


def main() -> int:
    for attempt in range(1,5):
        results=[check(path,kind) for path,kind in CHECKS]
        print(json.dumps({"attempt":attempt,"checks":results},ensure_ascii=False),flush=True)
        if all(row["ok"] for row in results):
            print("N8N_API_DEPLOYMENT_VERIFIED: landing, 10 QA, 104 G2B, no React Flow")
            print("N8N_MAIN_WORKER_LIVE_EXECUTION_NOT_VERIFIED")
            return 0
        if attempt<4:time.sleep(12)
    print("N8N_API_DEPLOYMENT_NOT_VERIFIED")
    return 1


if __name__=="__main__":
    sys.exit(main())
