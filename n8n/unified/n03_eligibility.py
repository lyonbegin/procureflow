"""N03: source-grounded bid qualification and required submission extractor.

This module analyses only actual text from N02 official HWP/PDF attachments.
It DOES NOT decide whether our company qualifies without its own evidence.
Every extracted rule keeps file sequence, SHA-256, and text line numbers.
"""
from __future__ import annotations
from hashlib import sha256
import re

QUAL_HEADING = re.compile(r"(?:^\s*\d{1,2}[.．]\s*입찰\s*(?:참여\s*)?자격\s*$|^\s*[【\[]?제?\d+조[】\]]?\s*입찰\s*(?:참여\s*)?자격)",re.I)
DOC_HEADING = re.compile(r"(?:입찰\s*참여\s*신청\s*서류|입찰\s*(?:서류|제출서류)\s*목록)")
DOC_STOP = re.compile(r"^\s*[【\[]\s*제\s*\d+\s*조\s*[】\]]")
SECTION_STOP = re.compile(r"^\s*\d{1,2}\.\s*(?:입찰|자격|제출|사업|선정|낙찰|계약|평가|안내|일정|기타)")
BULLET = re.compile(r"^\s*([가-하])[.．]\s*(.{4,})$")
NUMBERED = re.compile(r"^\s*(\d{1,2})[.．]\s*(.+)$")
DATE = re.compile(r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일(?:\s*[(（][^）)]{1,20}[）)])?(?:\s*\d{1,2}\s*시(?:\s*\d{1,2}\s*분)?)?")
SENSITIVE = [
    (re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),"[이메일 생략]"),
    (re.compile(r"(?<!\d)(?:0\d{1,2}[- ])\d{3,4}[- ]\d{4}(?!\d)"),"[연락처 생략]"),
    (re.compile(r"(?<!\d)\d{6}[- ]?[1-4]\d{6}(?!\d)"),"[식별번호 생략]"),
]

def _clean(text):
    value=re.sub(r"[\t\u00a0 ]+"," ",str(text or "")).strip()
    for rx,repl in SENSITIVE:
        value=rx.sub(repl,value)
    return value

def _evidence(seq,file_sha,start,end,text,kind):
    return {"category":kind,"text":_clean(text)[:450],"file_seq":seq,
            "source_file_sha256":file_sha,"line_start":start+1,"line_end":end+1}

def analyze(files,texts):
    """Only positionally verified text extractions; no synthetic claims."""
    eligible_files=[x for x in files if isinstance(x,dict)
                    and x.get("sha256") and x.get("text_chars")]
    # N02 downloads may contain errors or non-extracted files.
    if len(texts)!=len(eligible_files):
        raise ValueError("N03_TEXT_AND_ORIGINAL_MANIFEST_COUNT_MISMATCH")
    qualifications=[]
    documents=[]
    procedures=[]
    deadlines=[]
    source_files=[]
    for info,raw in zip(eligible_files,texts):
        if not isinstance(raw,str) or not raw.strip():
            continue
        # Re-check that text is actually associated with an official downloaded
        # source. SHA of source bytes remains the provenance ID from N02.
        seq=info["file_seq"]
        digest=str(info["sha256"])
        if not re.fullmatch("[0-9a-f]{64}",digest):
            raise ValueError("N03_INVALID_OFFICIAL_DOCUMENT_HASH")
        lines=[_clean(x) for x in raw.splitlines()]
        source_files.append({"file_seq":seq,"source_file_sha256":digest,
                             "text_sha256":sha256(raw.encode("utf-8")).hexdigest(),
                             "extracted_chars":len(raw),
                             "source":info.get("source"),
                             "format":info.get("format")})
        # Only accept participation requirements underneath an actual heading.
        for i,line in enumerate(lines):
            if not QUAL_HEADING.search(line):continue
            section=[]
            for j in range(i+1,min(i+22,len(lines))):
                row=lines[j]
                if SECTION_STOP.search(row) or DOC_STOP.search(row):break
                section.append((j,row))
            for n,(j,row) in enumerate(section):
                match=BULLET.search(row)
                if match:
                    continuation=[]
                    for k,more in section[n+1:n+3]:
                        if BULLET.search(more) or more.startswith(("※","7.","【")):break
                        if more and len(more)>7:continuation.append((k,more))
                    end=continuation[-1][0] if continuation else j
                    value=" ".join([row]+[v for _,v in continuation])
                    if not any(v["text"]==_clean(value)[:450] for v in qualifications):
                        qualifications.append(_evidence(seq,digest,j,end,value,"participation_rule"))
            # A separate unnumbered "공동참여 불가" line is important evidence,
            # but only when inside the explicit participation heading.
            for j,row in section:
                if re.search(r"공동\s*(?:참여|수급)\s*불가",row) and not any(
                   "공동참여 불가" in v["text"] and v["file_seq"]==seq for v in qualifications):
                    qualifications.append(_evidence(seq,digest,j,j,row,"no_joint_bid"))
            break
        for i,line in enumerate(lines):
            if not DOC_HEADING.search(line):continue
            # Strongest form: a defined article with numbered required documents.
            if not (re.search(r"제\s*\d+\s*조",line) or re.match(r"^\s*\d+[.．]",line)):
                continue
            for j in range(i+1,min(i+45,len(lines))):
                row=lines[j]
                if DOC_STOP.search(row) and j>i+1:break
                match=NUMBERED.search(row)
                if not match:continue
                number=int(match.group(1))
                if not 1<=number<=30 or not match.group(2).strip():continue
                if any(x.get("number")==number and x["text"]==_clean(row)[:450] for x in documents):continue
                entry=_evidence(seq,digest,j,j,row,"required_document")
                entry["number"]=number
                documents.append(entry)
            if documents:break
        # Actual procedural restrictions are captured with source anchors.
        proc_patterns=(
            ("no_joint_bid",r"공동\s*(?:참여|수급)\s*불가|컨소시엄\s*불가"),
            ("visit_submission",r"(?:방문|직접)\s*제출"),
            ("no_mail_or_fax",r"(?:우편|팩스)\s*(?:및|또는|,|\s)*\s*(?:팩스|우편)?\s*(?:접수\s*)?불가|우편\s*및\s*팩스\s*접수\s*불가"),
            ("electronic_bid",r"(?:나라장터|전자조달시스템).*?(?:투찰|전자입찰|입찰가격)"),
            ("sealed_price_envelope",r"별도\s*밀봉\s*제출"),
        )
        for kind,rx in proc_patterns:
            for i,line in enumerate(lines):
                if re.search(rx,line):
                    # Preserve only document-grounded evidence and avoid
                    # treating procedural notes as our firm's compliance.
                    if not any(x["category"]==kind for x in procedures):
                        procedures.append(_evidence(seq,digest,i,i,line,kind))
                    break
        for i,line in enumerate(lines):
            if "입찰 마감" in line or "입찰마감" in line:
                match=DATE.search(line)
                if match and not any(x["text"]==match.group() for x in deadlines):
                    item=_evidence(seq,digest,i,i,match.group(),"bid_deadline")
                    deadlines.append(item)
    found=bool(qualifications)
    return {
        "source":"downloaded_official_attachment_text_only",
        "document_requirement_extraction":"verified" if found else "not_verified",
        "qualification_rules":qualifications[:40],
        "required_documents":documents[:45],
        "procedural_conditions":procedures,
        "bid_deadlines":deadlines[:5],
        "qualification_rule_count":len(qualifications),
        "required_document_count":len(documents),
        "source_files":source_files,
        "document_text_chars":sum(len(t) for t in texts),
        "company_eligibility":"NOT_VERIFIED_NO_COMPANY_ORIGINAL",
        "company_eligibility_verified":False,
        "missing_company_evidence":["정비사업전문관리업 등록 증빙 등 공고 자격에 맞는 업체 증빙",
                                    "실적·인력·재무·국세·지방세 및 기타 원문 요구서류"],
        "reason":("OFFICIAL_DOCUMENT_REQUIREMENTS_EXTRACTED_COMPANY_EVIDENCE_UNAVAILABLE"
                 if found else "QUALIFICATION_SECTION_NOT_VERIFIED_IN_EXTRACTED_ORIGINALS")
    }
