"""Read-only public tender document acquisition and textual evidence extraction.

Files are downloaded only from verified government source hosts, checksummed
and stored in PostgreSQL. Unsupported HWP binaries remain explicit partials,
never misreported as parsed. Attachments are NOT a bid submission.
"""
from __future__ import annotations
from hashlib import sha256
from io import BytesIO
from urllib.parse import urlparse
from urllib.request import Request,urlopen
import json,re,zipfile,xml.etree.ElementTree as ET
from db import session

MAX_FILE=18*1024*1024
MAX_TEXT=800000
HOSTS={"www.g2b.go.kr","g2b.go.kr","nuri.g2b.go.kr",
       "apis.data.go.kr"}
SUPPORTED={"pdf","docx","xlsx","hwpx","txt","csv","xml","json"}
def ensure_documents():
    with session() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_case_documents(
          bid_no text NOT NULL,bid_ord text NOT NULL,
          file_id text NOT NULL,filename text NOT NULL DEFAULT '',
          url text NOT NULL,sha256 text NOT NULL,
          mime text NOT NULL DEFAULT '',size_bytes int NOT NULL,
          data bytea,extracted_text text NOT NULL DEFAULT '',
          extraction_state text NOT NULL,
          source_verified boolean NOT NULL DEFAULT false,
          fetched_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY(bid_no,bid_ord,file_id))""")
        c.execute("""CREATE INDEX IF NOT EXISTS ix_pf_document_sha
                ON procureflow.g2b_case_documents(sha256)""")

def _text_from_xml(raw):
    root=ET.fromstring(raw)
    out=[]
    for node in root.iter():
        if node.text and node.text.strip():
            out.append(node.text.strip())
    return "\n".join(out)[:MAX_TEXT]

def _xlsx(raw):
    with zipfile.ZipFile(BytesIO(raw)) as z:
        shared=[]
        if "xl/sharedStrings.xml" in z.namelist():
            r=ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared=["".join(x.itertext()) for x in r]
        out=[]
        for name in sorted(x for x in z.namelist()
                           if re.fullmatch(r"xl/worksheets/sheet\d+\.xml",x))[:50]:
            root=ET.fromstring(z.read(name))
            out.append("## "+name)
            for row in root.iter():
                if row.tag.rsplit("}",1)[-1]!="row":continue
                cells=[]
                for cell in row:
                    if cell.tag.rsplit("}",1)[-1]!="c":continue
                    value=""
                    for node in cell.iter():
                        if node.tag.rsplit("}",1)[-1]=="v":
                            value=node.text or ""
                    if cell.attrib.get("t")=="s" and value.isdigit():
                        index=int(value)
                        value=shared[index] if index<len(shared) else value
                    if value:cells.append(value)
                if cells:out.append("\t".join(cells))
                if sum(map(len,out))>=MAX_TEXT:break
        return "\n".join(out)[:MAX_TEXT]

def extract_file(filename,raw):
    ext=filename.rsplit(".",1)[-1].lower() if "." in filename else ""
    if len(raw)>MAX_FILE:return "oversized",""
    if ext=="pdf":
        from pypdf import PdfReader
        rdr=PdfReader(BytesIO(raw),strict=False)
        pages=[p.extract_text() or "" for p in rdr.pages[:180]]
        return ("parsed" if any(pages) else "pdf_scanned_text_unavailable",
                "\n".join(pages)[:MAX_TEXT])
    if ext=="docx":
        with zipfile.ZipFile(BytesIO(raw)) as z:
            return "parsed",_text_from_xml(z.read("word/document.xml"))
    if ext=="xlsx":return "parsed",_xlsx(raw)
    if ext=="hwpx":
        with zipfile.ZipFile(BytesIO(raw)) as z:
            files=sorted(k for k in z.namelist()
                         if k.startswith("Contents/section") and k.endswith(".xml"))
            text="\n".join(_text_from_xml(z.read(k)) for k in files[:100])
            return ("parsed" if text.strip() else "hwpx_empty",text[:MAX_TEXT])
    if ext in ("txt","csv","json","xml"):
        for encoding in ("utf-8-sig","cp949"):
            try:return "parsed",raw.decode(encoding)[:MAX_TEXT]
            except UnicodeDecodeError:pass
        return "unknown_encoding",""
    if ext=="hwp":
        from g2b_hwp5 import extract_hwp5
        return extract_hwp5(raw,MAX_TEXT)
    return "unsupported_document_format",""

def _government(url):
    p=urlparse(url)
    return p.scheme=="https" and p.hostname in HOSTS and (
        p.username is None and p.password is None)

def acquire_one(bid_no,bid_ord,file_id):
    ensure_documents()
    if not re.fullmatch(r"R\d{2}BK\d{8}",bid_no or ""):
        raise ValueError("current genuine G2B bid ID required")
    with session() as c:
        file=c.execute("""SELECT file_label,source_url FROM
               procureflow.g2b_notice_source_files
               WHERE bid_no=%s AND bid_ord=%s AND file_id=%s""",
               (bid_no,bid_ord,file_id)).fetchone()
    if not file:raise LookupError("source file must be listed by official notice first")
    url=file["source_url"]
    if not _government(url):raise ValueError("government host only")
    request=Request(url,headers={"Accept":"application/octet-stream",
                             "User-Agent":"ProcureFlow-document/1.0"})
    with urlopen(request,timeout=25) as resp:
        if not _government(resp.url):raise ValueError("non-government redirect blocked")
        content_type=resp.headers.get("content-type","")[:120]
        raw=resp.read(MAX_FILE+1)
        cd=resp.headers.get("content-disposition","")
    if len(raw)>MAX_FILE:raise ValueError("file exceeds 18MB limit")
    name=file["file_label"]
    if "filename=" in cd:
        name=cd.split("filename=",1)[1].split(";",1)[0].strip('" ')
    if "." not in name or name in ("stdNtceDocUrl","bidNtceDtlUrl"):
        name=urlparse(resp.url).path.rsplit("/",1)[-1]
    if not name or "." not in name:
        status,text="downloaded_unidentified_format",""
    else:
        try:status,text=extract_file(name,raw)
        except Exception as exc:
            status="extract_error_"+type(exc).__name__;text=""
    digest=sha256(raw).hexdigest()
    with session() as c:
        c.execute("""INSERT INTO procureflow.g2b_case_documents
             (bid_no,bid_ord,file_id,filename,url,sha256,mime,size_bytes,
              data,extracted_text,extraction_state,source_verified)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true)
             ON CONFLICT(bid_no,bid_ord,file_id) DO UPDATE SET
                filename=excluded.filename,url=excluded.url,
                sha256=excluded.sha256,mime=excluded.mime,
                size_bytes=excluded.size_bytes,data=excluded.data,
                extracted_text=excluded.extracted_text,
                extraction_state=excluded.extraction_state,
                source_verified=true,fetched_at=now()
        """,(bid_no,bid_ord,file_id,name[:250],url,digest,content_type,len(raw),
             raw,text,status))
        c.execute("""UPDATE procureflow.g2b_notice_source_files
             SET content_sha=%s,bytes_size=%s,state=%s,last_seen=now()
             WHERE bid_no=%s AND bid_ord=%s AND file_id=%s
        """,(digest,len(raw),status,bid_no,bid_ord,file_id))
    return {"bid_no":bid_no,"file_id":file_id,"filename":name,
            "bytes":len(raw),"sha256":digest,"state":status,
            "extracted_chars":len(text),"source":url,"submitted":False}

def list_documents(bid_no,bid_ord="000"):
    ensure_documents()
    with session() as c:
        index=c.execute("""SELECT file_id,file_label,source_url,content_sha,
                           bytes_size,state FROM procureflow.g2b_notice_source_files
                           WHERE bid_no=%s AND bid_ord=%s
                           ORDER BY file_id""",(bid_no,bid_ord)).fetchall()
        docs=c.execute("""SELECT file_id,filename,url,sha256,mime,size_bytes,
                         octet_length(data) AS bytes_saved,source_verified,
                         length(extracted_text) AS extracted_chars,
                         extraction_state,fetched_at
                         FROM procureflow.g2b_case_documents
                         WHERE bid_no=%s AND bid_ord=%s ORDER BY file_id
                     """,(bid_no,bid_ord)).fetchall()
    indexed={x["file_id"] for x in index}
    valid={x["file_id"] for x in docs
           if x["file_id"] in indexed and x["source_verified"]
           and x["sha256"] and len(x["sha256"])==64
           and (x["size_bytes"] or 0)>0
           and x["size_bytes"]==x["bytes_saved"]}
    complete=bool(indexed) and valid==indexed
    return {"bid_no":bid_no,"files_listed":len(index),
            "files_downloaded":len(valid),"original_index":index,
            "downloaded":docs,
            "all_listed_files_obtained":complete,
            "all_documents_text_extracted":complete and all(
                x["extraction_state"]=="parsed" and (x["extracted_chars"] or 0)>0
                for x in docs if x["file_id"] in indexed),
            "invalid_or_missing_file_ids":sorted(indexed-valid)}
