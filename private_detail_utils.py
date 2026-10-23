"""Extract evidence-backed, public supplier and portfolio detail (not list labels).

No account credentials, guessed company identities or masked fields.
Retain originals for auditing; expose only public page sections and metadata.
"""
import re
from urllib.parse import urlparse,urljoin

SECTIONS=("기본정보","포트폴리오","수행내역","기술정보","경력정보","인터뷰",
          "활동 요약","보유기술","프로젝트 배경","프로젝트 성과","프로젝트 내용",
          "담당 업무","구현 기능","기술 스택","프로젝트 기간","진행 과정",
          "고객사","작업 범위")
TECH=("Python","JavaScript","TypeScript","Node.js","React Native","React","Next.js",
      "Vue","Angular","Flutter","Kotlin","Swift","Spring","Java","PHP","AWS",
      "Azure","GCP","PostgreSQL","MySQL","MongoDB","Docker","Kubernetes",
      "Figma","Photoshop","Illustrator","HTML","CSS","AI","LLM","iOS","Android",
      "OpenAI","Django","FastAPI","Redis","Unity","C#","C++","TensorFlow","PyTorch")
HIDE_SELECTORS=(
  ".modalPreWrap",".modal-pre-wrap",".modalPre",".modal",".terms-modal",
  "footer","script","style","noscript","[aria-hidden='true']"
)

def parse_public_sections(text):
    text=(text or "").replace("\r","").strip()
    cleaned=re.sub(r"\n{4,}","\n\n",text)
    # Terms and modal template text can exceed the real profile. Truncate it,
    # rather than presenting the terms of use as a technical portfolio.
    cuts=[cleaned.find(x) for x in ("제 1 조 (목적) :::","선택 파트너스 4개 팀","고객센터 : 02-6497-3300")]
    valid=[x for x in cuts if x>=350]
    if valid:cleaned=cleaned[:min(valid)].rstrip()
    sections={}
    for term in SECTIONS:
        idx=cleaned.find(term)
        if idx>=0:
            # Keep a bounded contextual excerpt, not invented structured facts.
            excerpt=cleaned[idx+len(term):idx+len(term)+2100].strip()
            if excerpt:sections[term]=excerpt
    technologies=[s for s in TECH if re.search(r"(?<![\w])"+re.escape(s)+r"(?![\w])",cleaned,re.I)]
    return {"text":cleaned[:75000],"sections":sections,
            "technologies":technologies,"body_length":len(cleaned)}

def public_page_extract(page):
    """Only browser-visible text and publicly rendered image/link metadata."""
    data=page.evaluate("""() => {
       const ban=['.modalPreWrap','.modal-pre-wrap','.terms-modal',
                  'footer','script','style','noscript','[aria-hidden="true"]'];
       const root=document.body.cloneNode(true);
       for(const s of ban){for(const n of root.querySelectorAll(s)){n.remove()}}
       const text=(root.innerText||root.textContent||'').trim();
       const imgs=[...document.querySelectorAll('img[src]')]
           .filter(x=>x.getClientRects().length)
           .slice(0,60).map(x=>({alt:(x.alt||'').slice(0,140),
                                      url:(x.currentSrc||x.src||'').slice(0,500)}))
           .filter(x=>x.url.startsWith('https://'));
       const links=[...document.querySelectorAll('a[href]')]
           .filter(x=>x.getClientRects().length)
           .slice(0,180).map(x=>({text:(x.innerText||'').trim().slice(0,110),
                                url:x.href||''}))
           .filter(x=>x.url.startsWith('https://'));
       const headings=[...document.querySelectorAll('h1,h2,h3')]
           .filter(x=>x.getClientRects().length)
           .map(x=>(x.innerText||'').trim()).filter(Boolean).slice(0,40);
       return {text,images:imgs,links,headings,
               title:document.title||''};
    }""")
    parsed=parse_public_sections(data["text"])
    parsed.update({"images":data["images"],"links":data["links"],
                   "headings":data["headings"],"page_title":data["title"]})
    return parsed

def validated_public_url(url,host):
    u=urlparse(url)
    return u.scheme=="https" and u.hostname in (host,host.removeprefix("www."))
