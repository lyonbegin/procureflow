"""N03 source-only capture of tender requirements from N02 official originals.

No AI, bidder-eligibility decision, price recommendation or fabricated conditions.
Every returned quotation is anchored to an actual original file SHA-256 and a
logical extracted line number. Logical lines are NOT PDF page line numbers.
"""
from __future__ import annotations
from hashlib import sha256
from io import BytesIO
import re
import struct
import zipfile
import zlib

MAX_EXTRACT_CHARS=240_000
MAX_EVIDENCE_PER_CATEGORY=28
MAX_EXCERPT_CHARS=780
CATEGORIES={
 "submission_forms":r"별지\s*(?:제\s*)?\d+\s*호|입찰\s*(?:참여|참가)?\s*신청서|제출\s*서류|입찰\s*서류|(?:첨부|제출)\s*서식|이행각서|견적서|실적증명서",
 "scope_of_work":r"과업\s*(?:내용|범위|지시|목적|수행)|(?:용역|업무)\s*(?:내용|범위|개요)|수행\s*(?:업무|범위|과제)|주요\s*업무|사업\s*(?:내용|범위|개요)",
 "evaluation_criteria":r"평가\s*(?:기준|항목|배점|표|방법)|배점표|적격\s*심사|심사\s*(?:배점|기준)|기술\s*평가|가격\s*평가|제안서\s*평가",
 "participation_requirements":r"입찰\s*(?:참가|참여)\s*(?:자격|조건)|참가\s*자격|응찰\s*자격|자격\s*(?:요건|제한)|공동\s*(?:도급|참여|수급)|컨소시엄",
 "submission_deadlines":r"(?:제출|접수|입찰|투찰)\s*(?:기한|일시|기간|마감)|마감\s*(?:일시|일자|기한)|접수\s*기간|입찰\s*일정",
 "submission_methods":r"제출\s*(?:방법|장소|처)|(?:방문|직접|전자)\s*제출|전자\s*(?:입찰|투찰)|우편\s*(?:접수|제출)|밀봉\s*제출|나라장터|전자조달|USB",
}
PATTERNS={k:re.compile(v,re.I) for k,v in CATEGORIES.items()}
HEADING=re.compile(r"^\s*(?:제?\s*\d{1,2}\s*[조.．]|[가-하]\s*[.．]|[①-⑳]|【)")
MAX_PDF_PAGES=120
MAX_HWP_SECTIONS=32

def _extract_pdf(raw):
    from pypdf import PdfReader
    reader=PdfReader(BytesIO(raw))
    texts=[]
    chars=0
    pages=0
    for page in reader.pages[:MAX_PDF_PAGES]:
        pages+=1
        chunk=page.extract_text() or ""
        texts.append(chunk)
        chars+=len(chunk)
        if chars>=MAX_EXTRACT_CHARS:break
    return "\n".join(texts)[:MAX_EXTRACT_CHARS],"pdf",(
        len(reader.pages)>pages or chars>MAX_EXTRACT_CHARS)

def _extract_hwp(raw):
    import olefile
    if not olefile.isOleFile(BytesIO(raw)):
        raise ValueError("HWP5_INVALID_OLE")
    pieces=[]
    char_count=0
    limited=False
    with olefile.OleFileIO(BytesIO(raw)) as ole:
        if not ole.exists("FileHeader"):raise ValueError("HWP5_HEADER_MISSING")
        header=ole.openstream("FileHeader").read(40)
        if len(header)<40:raise ValueError("HWP5_HEADER_SHORT")
        compressed=bool(struct.unpack("<I",header[36:40])[0]&1)
        sections=sorted(
            (p for p in ole.listdir()
             if len(p)==2 and p[0]=="BodyText" and p[1].startswith("Section")),
            key=lambda p:int(re.search(r"\d+$",p[-1]).group())
                          if re.search(r"\d+$",p[-1]) else 0)
        if len(sections)>MAX_HWP_SECTIONS:limited=True
        for path in sections[:MAX_HWP_SECTIONS]:
            data=ole.openstream(path).read(12*1024*1024+1)
            if len(data)>12*1024*1024:
                limited=True
                break
            if compressed:
                d=zlib.decompressobj(-15)
                data=d.decompress(data,18*1024*1024)
                if not d.eof:limited=True
            i=0
            while i+4<=len(data):
                header=struct.unpack_from("<I",data,i)[0];i+=4
                tag=header&1023
                length=header>>20
                if length==4095:
                    if i+4>len(data):break
                    length=struct.unpack_from("<I",data,i)[0];i+=4
                if length>18*1024*1024 or i+length>len(data):break
                if tag==67:
                    t=data[i:i+length].decode("utf-16-le",errors="replace")
                    t=re.sub(r"[\x00-\x08\x0b-\x1f]"," ",t)
                    if t.strip():
                        pieces.append(t)
                        char_count+=len(t)+1
                i+=length
                if char_count>=MAX_EXTRACT_CHARS:
                    limited=True
                    break
            if limited:break
    return "\n".join(pieces)[:MAX_EXTRACT_CHARS],"hwp5",limited

def _extract_zip(raw):
    from xml.etree import ElementTree as ET
    with zipfile.ZipFile(BytesIO(raw)) as z:
        names=z.namelist()
        if "word/document.xml" in names:
            selected=["word/document.xml"]+[
                p for p in names if re.fullmatch(r"word/(?:header|footer)\d+\.xml",p)]
            kind="docx"
        else:
            selected=sorted(
                (p for p in names if re.fullmatch(r"Contents/(?:section|Section)\d+\.xml",p)),
                key=lambda p:int(re.search(r"\d+",p.rsplit("/",1)[-1]).group()))
            kind="hwpx"
        if not selected:
            raise ValueError("ZIP_HAS_NO_SUPPORTED_TEXT_PARTS")
        texts=[]
        chars=0
        limited=False
        for name in selected[:90]:
            if z.getinfo(name).file_size>16*1024*1024:
                limited=True
                continue
            root=ET.fromstring(z.read(name))
            # XML text nodes are source content, never generated summaries.
            text="\n".join(s.strip() for s in root.itertext()
                           if s and s.strip())
            texts.append(text)
            chars+=len(text)
            if chars>=MAX_EXTRACT_CHARS:
                limited=True
                break
        limited=limited or len(selected)>90
        return "\n".join(texts)[:MAX_EXTRACT_CHARS],kind,limited

def _extract_source(raw):
    if raw.startswith(b"%PDF"):return _extract_pdf(raw)
    if raw.startswith(b"\xd0\xcf\x11\xe0"):return _extract_hwp(raw)
    if raw.startswith(b"PK\x03\x04"):return _extract_zip(raw)
    if raw.startswith(b"\xef\xbb\xbf") or raw.startswith(b"<?xml"):
        return raw.decode("utf-8-sig")[:MAX_EXTRACT_CHARS],"text",len(raw)>MAX_EXTRACT_CHARS
    raise ValueError("UNSUPPORTED_ATTACHMENT_FOR_REQUIREMENT_TEXT")

def _logical_lines(text):
    text=text.replace("\r\n","\n").replace("\r","\n").replace("\u00a0"," ")
    # Add boundaries at visible numbering/annex markers when a HWP/XML reader
    # merges adjacent paragraphs. Do not alter the words or synthesize content.
    text=re.sub(r"(?=【\s*제\s*\d+\s*조\s*】)","\n",text)
    text=re.sub(r"(?<!\d)(별지\s*(?:제\s*)?\d+\s*호)","\n"+r"\1",text)
    text=re.sub(r"(?<!\d)([가-하])\s*[.．]\s*(?=[가-힣])",r"\n\1. ",text)
    out=[]
    for line in text.splitlines():
        line=re.sub(r"[ \t]+"," ",line).strip()
        if not line:continue
        if len(line)<=1000:out.append(line)
        else:
            # Preserve all text with stable, bounded logical segments.
            out.extend(line[i:i+1000] for i in range(0,len(line),1000))
    return out

def collect(files,read_original):
    """Read saved, SHA-verified N02 files; capture raw cited lines in 6 groups.

    Returns no legal/commercial evaluation, no assertion of compliance and
    no invented form names, deadlines, tasks or scores.
    """
    categories={key:[] for key in CATEGORIES}
    sources=[]
    gaps=[]
    if not files:
        return "partial",{
            "source":"N02_immutable_official_originals","categories":categories,
            "category_counts":{k:0 for k in categories},
            "source_files":[],"extracted_source_count":0,
            "missing_categories":list(categories),
            "gaps":["N02_no_official_attachments_to_read"],
            "business_evaluation_performed":False,
            "requirements_semantically_verified":False,
        }
    used=set()
    for file in files:
        seq=file.get("file_seq")
        checksum=str(file.get("sha256") or "")
        size=file.get("size_bytes")
        if not isinstance(seq,int) or seq in used or not re.fullmatch(r"[0-9a-f]{64}",checksum):
            raise ValueError("N03_INVALID_OFFICIAL_ORIGINAL_MANIFEST")
        used.add(seq)
        if not isinstance(size,int) or size<=0 or size>96*1024*1024:
            raise ValueError("N03_INVALID_ORIGINAL_SIZE")
        raw=read_original(file)
        if not isinstance(raw,bytes) or len(raw)!=size or sha256(raw).hexdigest()!=checksum:
            raise ValueError("N03_ORIGINAL_HASH_OR_SIZE_MISMATCH")
        entry={"file_seq":seq,"filename":file.get("original_filename"),
               "source_url":file.get("source"),"sha256":checksum,
               "size_bytes":size,"text_extracted":False,
               "text_truncated":False}
        try:
            text,kind,limited=_extract_source(raw)
            if not text.strip():raise ValueError("NO_TEXT_EXTRACTED")
            entry.update({"text_extracted":True,"format":kind,
                           "text_chars":len(text),"text_sha256":sha256(text.encode()).hexdigest(),
                           "text_truncated":limited})
            if limited:gaps.append("N03_document_text_truncated:"+str(seq))
            lines=_logical_lines(text)
            for index,line in enumerate(lines):
                for category,pattern in PATTERNS.items():
                    if not pattern.search(line) or len(categories[category])>=MAX_EVIDENCE_PER_CATEGORY:continue
                    snippet=line
                    if len(line)<90 and (HEADING.match(line) or line.endswith((":", "："))):
                        snippet=" ".join(lines[index:min(index+4,len(lines))])
                    categories[category].append({
                        "file_seq":seq,"source_file_sha256":checksum,
                        "source_text_sha256":entry["text_sha256"],
                        "filename":file.get("original_filename"),
                        "logical_line":index+1,"original_text":snippet[:MAX_EXCERPT_CHARS],
                        "excerpt_truncated":len(snippet)>MAX_EXCERPT_CHARS,
                        "text_line_basis":"extracted_logical_lines_not_printed_page_numbers"})
        except (ValueError,RuntimeError,ImportError,KeyError,EOFError,TypeError,zipfile.BadZipFile) as exc:
            entry["extraction_error"]=type(exc).__name__+":"+str(exc)[:100]
            gaps.append("N03_document_text_unavailable:"+str(seq))
        sources.append(entry)
    missing=[key for key,quotes in categories.items() if not quotes]
    gaps.extend("N03_missing_raw_evidence:"+key for key in missing)
    count=sum(1 for x in sources if x["text_extracted"])
    if count<len(files):gaps.append("N03_not_all_originals_text_extracted")
    return ("verified" if count==len(files) and not missing and
            not any(x["text_truncated"] for x in sources) else "partial"),{
        "source":"N02_immutable_official_originals",
        "categories":categories,
        "category_counts":{k:len(v) for k,v in categories.items()},
        "source_files":sources,
        "original_file_count":len(files),
        "extracted_source_count":count,
        "missing_categories":missing,
        "gaps":gaps,
        "business_evaluation_performed":False,
        "requirements_semantically_verified":False,
        "all_mandatory_submissions_identified":False,
    }
