"""READ-ONLY live region input DOM probe. Prints only public control metadata."""
import json,time,base64,io
from playwright.sync_api import sync_playwright
from g2b_bid_notice_site_search import (
 G2B_HOME,_navigate,_wait_for_site_rendered,_dismiss_public_notices,_frames
)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
 ctx=browser.new_context(locale="ko-KR",timezone_id="Asia/Seoul",viewport={"width":1440,"height":900})
 tab=ctx.new_page()
 tab.goto(G2B_HOME,wait_until="domcontentloaded",timeout=30000)
 if not _wait_for_site_rendered(tab):tab.reload(wait_until="domcontentloaded",timeout=30000)
 if not _wait_for_site_rendered(tab):raise RuntimeError("G2B_SITE_RENDERED_EMPTY")
 _navigate(tab)
 _dismiss_public_notices(tab)
 for frame in _frames(tab):
  try:
   data=frame.evaluate(r"""()=> {
    const re=/odnLmtLgdng|지역제한|지역 제한|참가자격|지역필터|지역|수요기관/i;
    const els=[...document.querySelectorAll('input,select,button,a,label,span,th,td')].filter(e=>{
      return re.test((e.id||'')+' '+(e.name||'')+' '+(e.title||'')+' '+(e.getAttribute('aria-label')||'')+' '+(e.tagName==='INPUT'?'':(e.innerText||'').slice(0,70)))
    }).slice(0,85);
    const describe=e=>({tag:e.tagName,id:(e.id||'').slice(0,150),
       name:(e.getAttribute('name')||'').slice(0,80),
       text:(e.tagName==='INPUT'?(e.value||''):(e.innerText||'')).trim().slice(0,95),
       title:(e.getAttribute('title')||'').slice(0,60),
       type:(e.getAttribute('type')||'').slice(0,40),
       readonly:!!e.readOnly,disabled:!!e.disabled,
       visible:!!e.getClientRects().length,
       parent:(e.parentElement?.outerHTML||'').slice(0,850)});
    return {title:document.title, matches:els.map(describe),
      potentialInputs:[...document.querySelectorAll('input,select')].filter(e=>/odnLmtLgdng/i.test(e.id||'')).map(describe)};
   }""")
   if data.get("matches"):
    print("REGION_LIVE_DOM",json.dumps({"frame":frame.url.split("?")[0][-120:],"data":data},
      ensure_ascii=False)[:16000],flush=True)
  except Exception as e:print("REGION_LIVE_DOM_ERROR",type(e).__name__,flush=True)
 try:
  raw=tab.screenshot(type="jpeg",quality=55,full_page=False)
  print("REGION_SCREEN_BASE64="+base64.b64encode(raw).decode(),flush=True)
 except Exception as e:print("REGION_SCREEN_ERROR",type(e).__name__,flush=True)
 ctx.close();browser.close()
