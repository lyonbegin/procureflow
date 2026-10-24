"""Read-only public Railway smoke verification used after a main-branch merge.

No credentials or DB writes. Never treat a GitHub merge as proof Railway
deployed successfully. Prints exact HTTP failures for troubleshooting.
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
TIMEOUT = 13
CHECKS = (
    ("/", "react-flow"),
    ("/health", "health"),
    ("/api/g2b/cases/R26BK01787028/features", "104-api"),
    ("/api/g2b/cases/R26BK01787028/workflow/plan", "planner"),
)


def check(path: str, kind: str) -> dict:
    url = BASE + path
    try:
        request = Request(url, headers={
            "User-Agent": "ProcureFlow-public-readonly-smoke/1.0",
            "Accept": "text/html,application/json",
        })
        with urlopen(request, timeout=TIMEOUT) as response:
            status = response.status
            content_type = response.headers.get("Content-Type", "")
            body = response.read(500_000).decode("utf-8", errors="replace")
        result = {"path": path, "kind": kind, "http_status": status,
                  "response_type": content_type, "ok": False}
        if kind == "react-flow":
            result["ok"] = ("id=\"root\"" in body and
                            "/studio/assets/" in body and status == 200)
            result["explanation"] = ("react-flow-bundle-linked" if result["ok"]
                                     else "React Flow assets not linked in homepage")
        elif kind == "health":
            content = json.loads(body)
            result["ok"] = status == 200 and content.get("status") == "ok"
            result["explanation"] = "DB reachable" if result["ok"] else "DB health check not ready"
        elif kind == "104-api":
            content = json.loads(body)
            result["ok"] = status == 200 and content.get("total") == 104                 and len(content.get("features", [])) == 104
            result["explanation"] = "all 104 live API contracts" if result["ok"]                 else "104 case endpoints unavailable, incomplete, or an older deployment"
        elif kind == "planner":
            content = json.loads(body)
            result["ok"] = (status == 200 and content.get("total_functions") == 104
                             and "recommended_next" in content)
            result["explanation"] = "live planner data" if result["ok"]                 else "recommended-workflow API missing or unhealthy"
        return result
    except HTTPError as err:
        return {"path": path, "kind": kind, "ok": False,
                "http_status": err.code, "error": "HTTPError"}
    except (URLError, TimeoutError, ValueError, OSError) as err:
        return {"path": path, "kind": kind, "ok": False,
                "error": type(err).__name__ + ": " + str(err)[:170]}


def main() -> int:
    tries = 3
    results = []
    for attempt in range(1, tries + 1):
        results = [check(path, kind) for path, kind in CHECKS]
        print(json.dumps({"attempt": attempt, "base": BASE,
                          "checks": results}, ensure_ascii=False), flush=True)
        if all(item["ok"] for item in results):
            print("LIVE_DEPLOYMENT_VERIFIED: React Flow, DB, 104 endpoints, planner")
            return 0
        if attempt < tries:
            time.sleep(8)
    print("LIVE_DEPLOYMENT_NOT_VERIFIED: see HTTP/connection diagnostics above")
    return 1


if __name__ == "__main__":
    sys.exit(main())
