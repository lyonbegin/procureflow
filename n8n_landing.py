"""Tiny workflow *launcher*, not an editor, DAG, or execution engine.

The only workflow UI/runner is n8n. Without a configured n8n URL we
show an explicit deployment blocker and read-only API simulation links;
never claim that a test executed inside n8n.
"""
from html import escape
import os
from urllib.parse import urlparse
from fastapi.responses import HTMLResponse


def editor_base() -> str:
    url = os.getenv("N8N_EDITOR_URL", "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        return ""
    return url


def scenario_editor_url(scenario_id: str) -> str:
    base = editor_base()
    if not base:
        return ""
    if not (len(scenario_id) == 3 and scenario_id.startswith("S")
            and scenario_id[1:].isdigit() and 1 <= int(scenario_id[1:]) <= 10):
        return ""
    return f"{base}/workflow/PFDEMO2026{scenario_id}WF"


def launcher() -> HTMLResponse:
    from n8n_scenarios import read_manifest
    base = editor_base()
    items = []
    for scenario in read_manifest()["scenarios"]:
        sid, title = scenario["id"], escape(scenario["title"])
        link = scenario_editor_url(sid)
        if link:
            action = (f'<a class="btn" target="_blank" rel="noopener noreferrer" '
                      f'href="{escape(link, quote=True)}">n8n에서 열고 실행</a>')
        else:
            action = '<span class="blocked">n8n 서버 연결 전 · 실행 불가</span>'
        items.append(
            f'<article><header><b>{sid}</b><strong>{title}</strong></header>'
            f'<p>단계 {len(scenario["steps"])}개 · 예상 {escape(scenario["expected"])}</p>'
            f'<div class="actions">{action}'
            f'<a class="quiet" href="/api/n8n/scenarios/{sid}/simulate" target="_blank">'
            'API 가상 결과 검사</a></div></article>'
        )
    status = ("n8n 연동 URL 설정됨 — 실행하려면 n8n 로그인 후 각 워크플로에서 "
              "<b>Execute workflow</b>를 누르세요. 워크플로가 실제로 가져와졌는지는 별도 확인 필요."
              if base else
              "n8n 인스턴스가 아직 이 API에 연결되지 않았습니다. "
              "<b>N8N_EDITOR_URL</b>과 n8n 워크플로 가져오기가 완료되기 전에는 실행 버튼을 표시하지 않습니다.")
    return HTMLResponse("""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProcureFlow · n8n 전용 워크플로 시나리오</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f8fb;font:14px/1.6 system-ui,'Malgun Gothic',sans-serif;color:#20374b}
nav{background:#0d3448;color:white;padding:15px max(24px,calc((100vw - 1110px)/2));font-weight:750}
main{max-width:1130px;margin:0 auto;padding:34px 18px 70px}h1{font-size:24px;letter-spacing:-.7px;margin:0 0 8px}
.subtitle{color:#607d8e;max-width:950px;margin:0 0 20px}
.status{padding:13px;border:1px solid #e5d3aa;background:#fffaed;color:#725d38;border-radius:11px;margin-bottom:25px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:12px}
article{background:#fff;border:1px solid #dbe5ed;border-radius:12px;padding:17px;box-shadow:0 1px 8px #16365009;display:flex;flex-direction:column}
article header{display:flex;gap:10px;align-items:flex-start}
article header b{background:#e5f3f2;color:#117a77;border-radius:6px;padding:2px 7px;font-size:12px;flex-shrink:0}
article header strong{font-size:13px}article p{font-size:11px;color:#69879a;margin:11px 0 17px}
.actions{margin-top:auto;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.btn{background:#11757c;color:#fff;border-radius:8px;padding:8px 11px;text-decoration:none;font-size:12px;font-weight:700}
.quiet{color:#386e86;text-decoration:none;font-size:12px;padding:8px 0}
.blocked{color:#967144;font-size:11px;border-radius:7px;background:#fff6e4;padding:7px}
section.note{margin-top:24px;color:#5b7789;background:white;border:1px solid #e1eaf1;border-radius:10px;padding:15px}
code{color:#174d6d}a:hover{text-decoration:underline}
</style></head><body><nav>ProcureFlow · n8n 단일 워크플로 플랫폼</nav><main>
<h1>10개 운영 시나리오</h1>
<p class="subtitle">각 시나리오는 n8n 고유의 <b>Manual Trigger → PF01~PF15 단계 노드 → 안전판정 → FastAPI 검증</b>으로 구성됩니다. n8n에서 실행하면 노드마다 실행 진행·입력·출력이 보입니다. 별도 React Flow나 자체 DAG 실행기는 사용하지 않습니다.</p>
<div class="status">""" + status + """</div>
<div class="grid">""" + "".join(items) + """</div>
<section class="note"><b>검증 구분</b>: ‘API 가상 결과 검사’는 FastAPI에서 메모리 데이터만 재계산합니다. n8n 실행 검증과 다르며 실제 나라장터·투찰은 수행하지 않습니다.<p>
<a href="/api/n8n/qa" target="_blank">10개 API 일괄 검사</a> ·
<a href="/api/n8n/scenarios" target="_blank">전체 n8n 워크플로 목록</a> ·
<a href="/operations">기존 발주 운영 조회</a></p></section></main></body></html>""",
        headers={"Cache-Control": "no-cache", "X-Robots-Tag":"noindex"})
