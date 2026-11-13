#!/usr/bin/env python3
"""Read-only, redacted diagnostics for live ChatGPT tabs after Web2API failure.

Never output URLs, page text, account details, cookies, prompts or responses.
"""
from playwright.sync_api import sync_playwright


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp("http://127.0.0.1:9222", timeout=15000)
        count=0
        for context in browser.contexts:
            for tab in context.pages:
                if tab.is_closed() or not tab.url.startswith("https://chatgpt.com"):
                    continue
                count+=1
                if count>6:
                    break
                try:
                    status=tab.evaluate("""() => {
                        const path=location.pathname;
                        const selector='div[role="textbox"]#prompt-textarea, div[role="textbox"].ProseMirror, textarea#prompt-textarea';
                        const composer=document.querySelector(selector);
                        const buttons=[...document.querySelectorAll('button')];
                        return {
                            route: path.includes('/auth/')?'login':path.startsWith('/c/')?'conversation':'home_or_other',
                            ready:document.readyState,
                            composer:Boolean(composer),
                            composer_length:composer?(composer.innerText||composer.value||'').length:0,
                            send_buttons:document.querySelectorAll('button[aria-label*="Send" i],button[type="submit"]').length,
                            stop_button:buttons.some(b=>(b.getAttribute('data-testid')||'').includes('stop')),
                            message_elements:document.querySelectorAll('[data-message-author-role]').length,
                            challenge:/(verify you are human|checking your browser|cloudflare)/i.test(document.body?.innerText?.slice(0,4000)||''),
                            body_length:(document.body?.innerText||'').length,
                            marker_occurrences:(document.body?.innerText||'').split('WEB2API_OK_7419').length-1,
                            articles:document.querySelectorAll('article').length,
                            main_elements:document.querySelectorAll('main').length,
                            markdown_nodes:document.querySelectorAll('.markdown').length,
                            turn_nodes:document.querySelectorAll('[data-testid*="conversation-turn"],[data-turn-id]').length,
                            message_testid:document.querySelectorAll('[data-testid*="message"]').length,
                            role_nodes:document.querySelectorAll('[data-message-author-role]').length,
                            message_id_nodes:document.querySelectorAll('[data-message-id]').length,
                            iframe_count:document.querySelectorAll('iframe').length,
                            marker_paths:(() => {
                                const found=[];
                                const walk=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
                                let n,scanned=0;
                                while((n=walk.nextNode())&&scanned++<10000&&found.length<4){
                                    if(!n.nodeValue?.includes('WEB2API_OK_7419')) continue;
                                    let parent=n.parentElement,chain=[];
                                    for(let i=0;parent&&i<7;i++,parent=parent.parentElement){
                                        const attrs={
                                            tag:parent.tagName?.toLowerCase()||'',
                                            role:parent.getAttribute('role')||'',
                                            testid:parent.getAttribute('data-testid')||'',
                                            classes:[...parent.classList].filter(x=>/^[a-zA-Z0-9_-]{2,50}$/.test(x)).slice(0,5)
                                        };
                                        if(!/^[a-zA-Z0-9_-]{0,60}$/.test(attrs.testid)) attrs.testid='other';
                                        chain.push(attrs);
                                    }
                                    found.push(chain);
                                }
                                return found;
                            })()
                        };
                    }""")
                    print("DIAG_CHATGPT_TAB_"+str(count)+"_ROUTE="+str(status.get("route")),flush=True)
                    for label,key in [("READY","ready"),("COMPOSER_PRESENT","composer"),("COMPOSER_LENGTH","composer_length"),("SEND_BUTTON_COUNT","send_buttons"),("STOP_BUTTON","stop_button"),("MESSAGE_ELEMENT_COUNT","message_elements"),("CHALLENGE_HINT","challenge")]:
                        print("DIAG_TAB_"+str(count)+"_"+label+"="+str(status.get(key)),flush=True)
                    for label,key in [
                        ("BODY_LENGTH","body_length"),("TEST_MARKER_OCCURRENCES","marker_occurrences"),
                        ("ARTICLE_COUNT","articles"),("MAIN_COUNT","main_elements"),
                        ("MARKDOWN_COUNT","markdown_nodes"),("TURN_NODES","turn_nodes"),
                        ("MESSAGE_TESTID_NODES","message_testid"),
                        ("ROLE_NODES","role_nodes"),("MESSAGE_ID_NODES","message_id_nodes"),
                        ("IFRAME_COUNT","iframe_count")
                    ]:
                        print("DIAG_TAB_"+str(count)+"_"+label+"="+str(status.get(key)),flush=True)
                    # Only structural tag/role/class metadata of the fixed TEST marker.
                    # Never output message text, link paths or user identifiers.
                    import json
                    print("DIAG_TAB_"+str(count)+"_TEST_MARKER_DOM_PATHS="+
                          json.dumps(status.get("marker_paths",[]),separators=(",",":")),flush=True)
                except Exception as exc:
                    print("DIAG_TAB_"+str(count)+"_READ_ERROR="+type(exc).__name__,flush=True)
        print("DIAG_CHATGPT_TAB_COUNT="+str(count),flush=True)
        browser.close()


if __name__=="__main__":
    main()
