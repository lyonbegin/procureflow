"""Minimal launcher only. n8n owns ALL workflow editing and executions."""
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
    if not base or not (len(scenario_id) == 3 and scenario_id.startswith("S")
            and scenario_id[1:].isdigit() and 1 <= int(scenario_id[1:]) <= 10):
        return ""
    return f"{base}/workflow/PFDEMO2026{scenario_id}WF"


def operational_editor_url(flow_id: str) -> str:
    base = editor_base()
    if not base or not (len(flow_id) == 4 and flow_id.startswith("PF")
            and flow_id[2:].isdigit() and 1 <= int(flow_id[2:]) <= 15):
        return ""
    return f"{base}/workflow/PFOP2026{flow_id}WF"


def _button(url: str) -> str:
    if not url:
        return '<span class="blocked">n8n 편집기 주소 미설정</span>'
    return ('<a class="btn" target="_blank" rel="noopener noreferrer" '
            f'href="{escape(url, quote=True)}">n8n에서 열고 실행</a>')


def launcher() -> HTMLResponse:
    from n8n_scenarios import read_manifest
    from n8n_operational import manifest
    flows = []
    for flow in manifest()["flows"]:
        fid = flow["id"]
        flows.append(
            '<article><header><b>' + fid + '</b><strong>' + escape(flow["label"]) +
            '</strong></header><p>실제 업무 기능 ' + str(len(flow["business_features"])) +
            '개 · 블록 ' + str(len(flow["owned_blocks"])) +
            '개 · DB 공식 증빙 읽기</p><div class="actions">' +
            _button(operational_editor_url(fid)) +
            f'<a class="quiet" target="_blank" href="/api/n8n/operational/flows/{fid}/inspect">'
            '실제 입력·출력·누락 확인</a>' +
            f'<a class="quiet" target="_blank" href="/api/n8n/operational/flows/{fid}/next-action">' +
            '다음 실제 수집계획·차단사유</a>' +
            f'<a class="quiet" href="/n8n/progress?flow={fid}">실제 작업 진행상황</a></div></article>'
        )
    demos = []
    for item in read_manifest()["scenarios"]:
        sid = item["id"]
        demos.append(
            '<article><header><b>' + sid + '</b><strong>' + escape(item["title"]) +
            '</strong></header><p>가상 운영 이벤트 ' + str(len(item["steps"])) +
            '개 · 예상 ' + escape(item["expected"]) +
            '</p><div class="actions">' + _button(scenario_editor_url(sid)) +
            f'<a class="quiet" target="_blank" href="/api/n8n/scenarios/{sid}/simulate">'
            'API 가상 결과 검사</a></div></article>'
        )
    status = ('추가 브라우저 로그인 없이 n8n 정식 편집기에 연결됩니다. n8n 관리자 계정이 설정되어 있으면 '
              '정식 노드 캔버스와 Execute workflow를 이용할 수 있습니다.'
              if editor_base() else
              'n8n은 외부 관리자 등록 위험 때문에 공개 접속이 차단돼 있습니다. '
              '관리자 소유권·인증 설정 전까지 실행 링크를 공개하지 않습니다.')
    native_editor = (
        '<section class="native-editor"><strong>실제 n8n 노드 편집기</strong>'
        '<p>이 페이지는 목록과 실제 증빙 조회용입니다. 노드 캔버스·선 연결·노드 입출력·'
        'Execute workflow 버튼은 아래 n8n 원본 편집기에서 사용합니다.</p>'
        '<p>별도의 브라우저 사용자 이름·비밀번호 입력창은 사용하지 않습니다. n8n 자체 로그인 상태에 따라 화면이 표시됩니다.</p>'
        f'<a class="btn" target="_blank" rel="noopener noreferrer" '
        f'href="{escape(editor_base(),quote=True)}">n8n 실제 노드 편집기 열기</a>'
        '</section>'
        if editor_base() else
        '<section class="native-editor"><strong>n8n 편집기 접근 준비 중</strong>'
        '<p>관리자 최초 등록을 공개하지 않도록 보안 게이트웨이를 설정 중입니다.</p></section>'
    )
    html = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ProcureFlow · n8n 단일 워크플로</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#f5f8fb;font:14px/1.6 system-ui,'Malgun Gothic',sans-serif;color:#20374b}
nav{background:#0d3448;color:white;padding:15px max(24px,calc((100vw - 1130px)/2));font-weight:750}
main{max-width:1130px;margin:0 auto;padding:34px 18px 70px}
h1{font-size:24px;letter-spacing:-.7px;margin:0 0 8px}
h2{font-size:22px;margin:34px 0 7px}
.subtitle{color:#607d8e;max-width:990px;margin:0 0 20px}
.status{padding:13px;border:1px solid #e5d3aa;background:#fffaed;color:#725d38;border-radius:11px;margin-bottom:25px}
.native-editor{padding:22px;border-radius:13px;background:#e5f3f1;border:1px solid #b8dad6;margin-bottom:28px}
.native-editor strong{font-size:19px}.native-editor p{margin:8px 0;color:#315a61;font-size:13px}
.native-editor .btn{display:inline-block;padding:12px 19px;font-size:15px;margin-top:8px}

.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
article{background:#fff;border:1px solid #dbe5ed;border-radius:12px;padding:17px;display:flex;flex-direction:column}
article header{display:flex;gap:10px;align-items:flex-start}
article header b{background:#e5f3f2;color:#117a77;border-radius:6px;padding:2px 7px;font-size:12px;flex-shrink:0}
article header strong{font-size:13px}
article p{font-size:11px;color:#69879a;margin:11px 0 17px}
.actions{margin-top:auto;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.btn{background:#11757c;color:white;border-radius:8px;padding:8px 11px;text-decoration:none;font-size:12px;font-weight:700}
.quiet{color:#386e86;text-decoration:none;font-size:12px;padding:8px 0}
.blocked{color:#967144;font-size:11px;border-radius:7px;background:#fff6e4;padding:7px}
section.note{margin-top:24px;color:#5b7789;background:white;border:1px solid #e1eaf1;border-radius:10px;padding:15px}
a:hover{text-decoration:underline}
</style></head><body><nav>ProcureFlow · n8n 단일 워크플로 플랫폼</nav>
<main><h1>ProcureFlow · 실제 n8n 노드 편집기</h1>
<p class="subtitle">노드를 배치·연결·실행하는 기능은 별도 상태 조회 화면이 아니라 n8n 정식 편집기에서 제공합니다.</p>
""" + native_editor + """
<h2>15개 실제 운영 플로우</h2>
<p class="subtitle">각 PF를 n8n으로 실행하면 공식 PostgreSQL 증빙과 43개 업무 블록의 입력·출력을 표시합니다. 기본값은 조회 전용이며, 관리자가 n8n Credential을 등록하고 collect 모드를 명시 선택한 경우에만 실제 Worker Job 1건을 실행합니다. 자동투찰은 하지 않습니다.</p>
<div class="status">""" + escape(status) + """</div>
<div class="grid">""" + "".join(flows) + """</div>
<h2>10개 운영 시나리오 (가상 검증)</h2>
<p class="subtitle">S01~S10은 가상의 정정·장애·자격·견적·경합 이벤트를 원본 업무와 구분해 실제 n8n 엔진에서 재생하는 테스트입니다. 기존 React Flow나 자체 DAG 실행기는 사용하지 않습니다.</p>
<div class="grid">""" + "".join(demos) + """</div>
<section class="note"><b>현재 운영 검증</b><p>
<a href="/api/n8n/native/status" target="_blank">n8n에 실제 등록·실행됐는지 확인</a> ·
<a href="/api/n8n/qa" target="_blank">10개 가상 검증</a> ·
<a href="/api/n8n/operational/flows" target="_blank">15개 운영 명세</a> ·
<a href="/operations">기존 업무 조회</a>
</p>공식 증빙이 누락되면 BLOCKED_OR_PENDING으로 유지됩니다. 승인 없는 업무 Job 등록·투찰은 수행하지 않습니다.</section>
</main></body></html>"""
    return HTMLResponse(html,headers={"Cache-Control":"no-cache","X-Robots-Tag":"noindex"})
