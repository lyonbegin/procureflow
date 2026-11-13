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
                            challenge:/(verify you are human|checking your browser|cloudflare)/i.test(document.body?.innerText?.slice(0,4000)||'')
                        };
                    }""")
                    print("DIAG_CHATGPT_TAB_"+str(count)+"_ROUTE="+str(status.get("route")),flush=True)
                    for label,key in [("READY","ready"),("COMPOSER_PRESENT","composer"),("COMPOSER_LENGTH","composer_length"),("SEND_BUTTON_COUNT","send_buttons"),("STOP_BUTTON","stop_button"),("MESSAGE_ELEMENT_COUNT","message_elements"),("CHALLENGE_HINT","challenge")]:
                        print("DIAG_TAB_"+str(count)+"_"+label+"="+str(status.get(key)),flush=True)
                except Exception as exc:
                    print("DIAG_TAB_"+str(count)+"_READ_ERROR="+type(exc).__name__,flush=True)
        print("DIAG_CHATGPT_TAB_COUNT="+str(count),flush=True)
        browser.close()


if __name__=="__main__":
    main()
