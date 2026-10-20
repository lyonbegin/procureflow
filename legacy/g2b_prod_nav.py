"""G2B navigation by WebSquare DOM elements (not screen visibility).

Independent Headless test only. It does not use Chrome 9333 and does not
manipulate popups. Uses the supplied WebSquare DOM ID suffixes and exact labels.
All click attempts and element counts are recorded in LAST_TRACE.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

G2B_ORIGIN = 'https://www.g2b.go.kr/'
API_PATH = '/pr/prc/prca/OderReq/selectOderReqList.do'
MENU_ROOT = '#mf_wfm_gnb_wfm_gnbMenu_genDepth1_0_btn_menuLvl1'
MENU_ORDER_LIST = '#mf_wfm_gnb_wfm_gnbMenu_genDepth1_0_genDepth2_0_btn_menuLvl2'
LAST_TRACE = []

# Operate on DOM nodes in their own document/frame, not screen coordinates.
# The submenu can legitimately be under a display:none wrapper before expansion.
DOM_SCRIPT = r'''({action,kind}) => {
  const docs = [document];
  // Open shadow-root fallback; regular WebSquare usually stays in document DOM.
  const all = [];
  const crawl = (root) => {
    for (const el of root.querySelectorAll('a,button,[role="button"]')) all.push(el);
    for (const el of root.querySelectorAll('*')) if (el.shadowRoot) crawl(el.shadowRoot);
  };
  crawl(document);
  const nameOf = e => (e.textContent || '').replace(/\s+/g,' ').trim();
  const rank = (e,kind) => {
    const id=e.id||'', cls=String(e.className||''), t=nameOf(e);
    const expected=kind==='root'?'발주':'발주목록';
    if (t!==expected) return -1;
    const suffix=kind==='root'?'genDepth1_0_btn_menuLvl1':'genDepth1_0_genDepth2_0_btn_menuLvl2';
    const general=kind==='root'?'btn_menuLvl1':'btn_menuLvl2';
    if (id==='mf_wfm_gnb_wfm_gnbMenu_'+suffix) return 100;
    if (id.endsWith(suffix)) return 90;
    if (id.includes('gnbMenu') && id.endsWith(general)) return 80;
    if (id.includes('gnbMenu') && cls.includes(kind==='root'?'depth1':'depth2')) return 60;
    // Site-map menu is a fallback only, not the first choice.
    if (id.includes('genMenu') && id.endsWith(kind==='root'?'btnMenu1':'btnMenu2')) return 20;
    return -1;
  };
  const candidates = all.map(e=>({e,score:rank(e,kind)})).filter(x=>x.score>=0)
       .sort((a,b)=>b.score-a.score);
  const short = e => {
    const style=getComputedStyle(e), r=e.getBoundingClientRect();
    return {id:e.id||'',tag:e.tagName,label:nameOf(e).slice(0,75),
      visible:style.visibility!=='hidden' && style.display!=='none' && !!e.getClientRects().length,
      display:style.display,parentDisplay:e.closest('.menu-content')?.style.display||'',
      onclickAttr:!!e.getAttribute('onclick'), score:rank(e,kind)};
  };
  const items=candidates.slice(0,6).map(x=>short(x.e));
  const expected=kind==='root'?'발주':'발주목록';
  const labelOnly=all.filter(e=>nameOf(e)===expected && rank(e,kind)<0).slice(0,8)
      .map(e=>({id:e.id||'',tag:e.tagName,label:nameOf(e),className:String(e.className||'').slice(0,120)}));
  if (action==='scan') return {found:candidates.length, items,
    allAnchors:all.length, exactTextButUnknownID:labelOnly};
  if (!candidates.length) return {clicked:false,reason:'DOM_ELEMENT_NOT_FOUND',items};
  const e=candidates[0].e;
  const info=short(e);
  try {
    // HTMLElement.click dispatches click on a DOM node independently of focus,
    // coordinates or parent display:none. WebSquare event handlers receive it.
    e.click();
    return {clicked:true,method:'HTMLElement.click',element:info,
      isTrusted:false,notes:'synthetic DOM click; server-side navigation still must be verified'};
  } catch(err) {
    return {clicked:false,reason:'DOM_CLICK_THROWN',error:String(err).slice(0,300),element:info};
  }
}'''


def _path(fr):
    try:
        p=urlsplit(fr.url)
        return p.path or '/' if p.scheme else fr.url[:70]
    except Exception:
        return '?'


def _frames(page):
    try: return list(page.frames)
    except Exception: return []


def _scan(pages, kind):
    results=[]
    for page in pages:
        for fr in _frames(page):
            try:
                r=fr.evaluate(DOM_SCRIPT,{'action':'scan','kind':kind})
                if r.get('found'):
                    results.append((page,fr,r))
            except Exception as exc:
                LAST_TRACE.append({'step':kind+'_scan_error','frame':_path(fr),'error':str(exc)[:190]})
    return results


def _click_dom(pages,kind):
    all_matches=_scan(pages,kind)
    LAST_TRACE.append({'step':kind+'_dom_scan', 'matches':[
        {'frame':_path(fr),'elements':r.get('items',[])} for _,fr,r in all_matches[:8]]})
    for page,fr,r in all_matches:
        try:
            outcome=fr.evaluate(DOM_SCRIPT, {'action':'click','kind':kind})
            LAST_TRACE.append({'step':kind+'_dom_click','frame':_path(fr),**outcome})
            if outcome.get('clicked'):
                return True
        except Exception as exc:
            LAST_TRACE.append({'step':kind+'_click_exception','frame':_path(fr),'error':str(exc)[:300]})
    return False


def _click_mouse_as_fallback(pages,kind):
    # If the site rejects synthetic events, try Playwright native click ON THE SAME
    # ELEMENT found in the correct frame. Never click arbitrary similarly-named text.
    sels=(('a[id$="genDepth1_0_btn_menuLvl1"]','a[id$="btn_menuLvl1"]')
          if kind=='root' else ('a[id$="genDepth1_0_genDepth2_0_btn_menuLvl2"]','a[id$="btn_menuLvl2"]'))
    label='발주' if kind=='root' else '발주목록'
    for page in pages:
        for fr in _frames(page):
            for sel in sels:
                try:
                    loc=fr.locator(sel)
                    for i in range(min(loc.count(),5)):
                        e=loc.nth(i)
                        if (e.text_content(timeout=600) or '').strip()!=label:continue
                        if not e.is_visible(): continue
                        e.click(timeout=1500)
                        LAST_TRACE.append({'step':kind+'_trusted_mouse_click','frame':_path(fr),'selector':sel,'ok':True})
                        return True
                except Exception as exc:
                    LAST_TRACE.append({'step':kind+'_trusted_mouse_fail','frame':_path(fr),'error':str(exc)[:150]})
    return False


def _form_present(fr):
    try:
        return bool(fr.evaluate(r'''() => {
          const p=location.pathname;
          if (/\/OderReq\//i.test(p) && !/selectOderReqList\.do$/i.test(p))return true;
          const txt=document.body?.innerText||'';
          const markers=['진행일자','진행기간','발주시기','업무구분','사업명','발주기관','검색조건','발주년월'];
          const score=markers.filter(x=>txt.includes(x)).length;
          const inputs=[...document.querySelectorAll('input,select,textarea')].filter(e=>e.getClientRects().length);
          const date=inputs.some(e=>/prgrsBgngYmd|prgrsEndYmd|oderStYm|oderEdYm|date|ymd/i.test(`${e.id} ${e.name} ${e.title}`));
          return (score>=2 && inputs.length>=2) || (score>=1 && date);
        }'''))
    except Exception:return False


def _search_click(fr):
    if not _form_present(fr): return False
    for sel in ('button:text-is("검색")', 'a:text-is("검색")',
                'input[type="button"][value="검색"]', 'input[type="submit"][value="검색"]',
                'button:has-text("검색")','a:has-text("검색")'):
        try:
            loc=fr.locator(sel)
            for i in range(min(loc.count(),15)):
                e=loc.nth(i)
                if not e.is_visible() or not e.is_enabled():continue
                txt=(e.get_attribute('value') or '') if sel.startswith('input') else (e.text_content(timeout=600) or '')
                if txt.strip() not in ('검색','검색하기','조회/검색'):continue
                id_=e.get_attribute('id') or ''
                if 'gnbMenu' in id_ or 'Sitemap' in id_: continue
                e.click(timeout=2000)
                LAST_TRACE.append({'step':'search_clicked','frame':_path(fr),'selector':sel})
                return True
        except Exception as exc:
            LAST_TRACE.append({'step':'search_click_failed','frame':_path(fr),'error':str(exc)[:150]})
    return False


def _pages(context):
    try: return [p for p in context.pages if not p.is_closed()]
    except Exception:return []


def _wait_and_search(context, attach_page, attached, timeout_s=20):
    deadline=time.monotonic()+timeout_s
    while time.monotonic()<deadline:
        pages=_pages(context)
        for page in pages:
            attach_page(page,attached)
            for fr in _frames(page):
                if _search_click(fr):return True
        if pages:pages[0].wait_for_timeout(350)
        else:time.sleep(.35)
    return False


def menu_snapshot(context):
    entries=[]
    for page in _pages(context):
        for fr in _frames(page):
            item={'path':_path(fr)}
            for name in ('root','submenu'):
                try:item[name]=fr.evaluate(DOM_SCRIPT,{'action':'scan','kind':name})
                except Exception as exc:item[name]={'error':str(exc)[:190]}
            try:
                item['title']=fr.evaluate('document.title')[:100]
            except Exception:pass
            entries.append(item)
    return entries


def safe_page_url(url):
    try:
        u=urlsplit(url)
        if u.scheme!='https' or u.hostname!='www.g2b.go.kr' or u.path.endswith('selectOderReqList.do'):return None
        return urlunsplit((u.scheme,u.netloc,u.path or '/','',''))
    except (TypeError,ValueError):return None


def remembered(path):
    try:return safe_page_url(json.loads(Path(path).read_text(encoding='utf-8')).get('search_url'))
    except (OSError,ValueError,TypeError):return None


def remember(path, url):
    """Compatibility with the production XHR bridge.

    The route hint is optional. It must never prevent the successfully captured
    search response from being written to SQLite. Store only a site URL, not
    cookies, tokens, XHR bodies, or user session data.
    """
    target = safe_page_url(url)
    if not target or target.rstrip('/') == G2B_ORIGIN.rstrip('/'):
        return False
    cache = Path(path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    temp = cache.with_name(cache.name + '.tmp')
    temp.write_text(json.dumps({'search_url': target}, ensure_ascii=False), encoding='utf-8')
    temp.replace(cache)
    return True


def auto_open_and_search(browser, cache_path, attach_page, attached):
    LAST_TRACE.clear()
    contexts=list(browser.contexts)
    if not contexts:return {'ok':False,'stage':'no_browser_context'}
    ctx=contexts[0]
    pages=_pages(ctx)
    for page in pages:attach_page(page,attached)
    for page in pages:
        if safe_page_url(page.url):
            for fr in _frames(page):
                if _search_click(fr):return {'ok':True,'stage':'search_clicked','mode':'existing_form', 'message':'기존 발주목록 화면에서 검색 클릭 완료'}
    page=next((p for p in pages if safe_page_url(p.url)),None) or (pages[0] if pages else ctx.new_page())
    attach_page(page,attached)
    if not safe_page_url(page.url) and not _scan(_pages(ctx),'root'):
        page.goto(G2B_ORIGIN,wait_until='domcontentloaded',timeout=30000)
    # WebSquare may build GNB asynchronously; don't require visible locators.
    deadline=time.monotonic()+14
    while time.monotonic()<deadline and not _scan(_pages(ctx),'root'):
        page.wait_for_timeout(350)
    LAST_TRACE.append({'step':'before_root', 'frames':menu_snapshot(ctx)})
    if not _click_dom(_pages(ctx),'root'):
        if not _click_mouse_as_fallback(_pages(ctx),'root'):
            return {'ok':False,'stage':'root_dom_not_found','message':'발주 DOM 엘리먼트를 찾지 못했습니다. menu_trace 확인'}
    # Search every frame afresh after root clicked. No stale frame reference.
    deadline=time.monotonic()+8
    found=False
    while time.monotonic()<deadline:
        if _scan(_pages(ctx),'submenu'):
            found=True;break
        page.wait_for_timeout(350)
    LAST_TRACE.append({'step':'after_root','frames':menu_snapshot(ctx)})
    if not found:
        # A site may only open the submenu on a trusted physical mouse event.
        _click_mouse_as_fallback(_pages(ctx),'root')
        page.wait_for_timeout(400)
    if not _click_dom(_pages(ctx),'submenu'):
        if not _click_mouse_as_fallback(_pages(ctx),'submenu'):
            return {'ok':False,'stage':'submenu_dom_not_found','message':'발주목록 DOM 엘리먼트 없음. frames / id 검색결과 확인'}
    if _wait_and_search(ctx,attach_page,attached,timeout_s=12):
        return {'ok':True,'stage':'search_clicked','mode':'dom_click', 'message':'발주 → 발주목록 → 검색 클릭 완료'}
    # JS click was delivered but WebSquare may require a trusted pointer event.
    # Use the identified visible node only, after the DOM strategy has failed.
    if _click_mouse_as_fallback(_pages(ctx),'submenu'):
        if _wait_and_search(ctx,attach_page,attached,timeout_s=7):
            return {'ok':True,'stage':'search_clicked','mode':'trusted_click_fallback','message':'실제 마우스 이벤트로 발주목록 검색 클릭 완료'}
    LAST_TRACE.append({'step':'after_submenu','frames':menu_snapshot(ctx)})
    return {'ok':False,'stage':'search_form_not_found',
            'message':'발주목록 DOM 클릭은 완료했으나 실제 검색 폼이 열리지 않았습니다.'}
