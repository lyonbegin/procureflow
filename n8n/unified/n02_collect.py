"""N02: download every available official G2B notice attachment and save originals.

This stage ONLY acquires and catalogs source files. It does not OCR, parse,
classify bidders, judge qualifications, or evaluate document contents.

The official download endpoint returns 422 for an absent fileSeq. An
explicit three-index 422 run is required to close enumeration, and the
method/scope is preserved in the manifest. Other errors never count as
an empty list or successful full collection.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from html import unescape
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, unquote
from urllib.request import Request
from zoneinfo import ZoneInfo
import json
import os
import re
import unicodedata
import uuid

OFFICIAL="https://www.g2b.go.kr"
DOWNLOAD=OFFICIAL+"/pn/pnp/pnpe/UntyAtchFile/downloadFile.do"
STORAGE_ROOT=Path(os.environ.get("PROCUREFLOW_ATTACHMENT_ROOT","/data/n01/bids"))
MAX_FILES=64
MAX_FILE_BYTES=96*1024*1024
MAX_COLLECTION_BYTES=450*1024*1024
END_MISSING_RUN=3
FILE_NAME_MAX=170
CONTENT_DISPOSITION_MAX=1000

class InventoryError(RuntimeError):
    pass

def _now():
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()

def _safe_name(raw):
    value=unicodedata.normalize("NFC",unescape(unquote(str(raw or ""))))
    # The original is retained only as display text; storage uses safe basename.
    value=value.replace("\\","/").rsplit("/",1)[-1]
    value=re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]',"_",value).strip(" .")
    if value in (".","..") or not value:value="이름미확인.bin"
    return value[:FILE_NAME_MAX].rstrip(" .") or "이름미확인.bin"

def _filename(disposition):
    value=str(disposition or "")[:CONTENT_DISPOSITION_MAX]
    match=re.search(r"filename\*\s*=\s*(?:[\"']?)([^;\r\n]+)",value,re.I)
    if match:
        raw=match.group(1).strip().strip('"').strip("'")
        raw=raw.split("''",1)[-1]
        return _safe_name(raw),True
    match=re.search(r'filename\s*=\s*(?:"([^"]*)"|([^;\r\n]*))',value,re.I)
    if match:
        raw=(match.group(1) or match.group(2) or "").strip()
        return _safe_name(raw),True
    return "",False

def _kind(name,first,content_type):
    ext=Path(name).suffix.lower().lstrip(".")
    if ext in ("hwp","hwpx","pdf","doc","docx","xls","xlsx","ppt",
               "pptx","zip","txt","csv","xml","jpg","jpeg","png","gif",
               "tif","tiff","dwg","dxf","rar","7z"):
        return ext
    if first.startswith(b"%PDF"):return "pdf"
    if first.startswith(b"\xd0\xcf\x11\xe0"):return "ole"
    if first.startswith(b"PK\x03\x04"):return "zip"
    if first.startswith(b"\x89PNG"):return "png"
    if first.startswith(b"\xff\xd8\xff"):return "jpg"
    return ext or "기타"

def _ident(notice):
    if not isinstance(notice,dict):raise ValueError("N02_SELECTED_NOTICE_REQUIRED")
    no=str(notice.get("bid_no") or "").strip()
    order=str(notice.get("bid_ord") or "000").strip()
    bsne=str(notice.get("business_code") or "03").strip()
    if not re.fullmatch(r"(?:R\d{2}BK\d{8}|\d{11})",no):
        raise ValueError("N02_SELECTED_NOTICE_ID_INVALID")
    if not re.fullmatch(r"\d{3}",order):
        raise ValueError("N02_SELECTED_NOTICE_REVISION_INVALID")
    if not re.fullmatch(r"\d{1,3}",bsne):
        raise ValueError("N02_SELECTED_NOTICE_BUSINESS_CODE_INVALID")
    return no,order,bsne

def _manifest_save(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(".manifest-"+uuid.uuid4().hex+".tmp")
    try:
        tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)

def _download_one(opener,no,order,bsne,seq,folder,total_before):
    query=urlencode({"bidPbancNo":no,"bidPbancOrd":order,"fileType":"",
                     "fileSeq":seq,"prcmBsneSeCd":bsne})
    url=DOWNLOAD+"?"+query
    req=Request(url,method="GET",headers={
        "Accept":"application/octet-stream,*/*",
        "User-Agent":"ProcureFlow-Official-Attachment-Collector/1.0",
        "Referer":OFFICIAL+"/"})
    try:
        response=opener.open(req,timeout=25)
    except HTTPError as exc:
        if exc.code==422:
            return {"file_seq":seq,"not_found":True,"http_status":422}
        raise InventoryError("OFFICIAL_DOWNLOAD_HTTP_"+str(exc.code)) from exc
    with response:
        if response.status!=200:raise InventoryError("OFFICIAL_DOWNLOAD_HTTP_"+str(response.status))
        declared=int(response.headers.get("Content-Length") or 0)
        if declared>MAX_FILE_BYTES or total_before+declared>MAX_COLLECTION_BYTES:
            raise InventoryError("OFFICIAL_ATTACHMENT_EXCEEDS_STORAGE_LIMIT")
        original,has_filename=_filename(response.headers.get("Content-Disposition"))
        if not original:original=f"첨부_{seq:03d}.bin"
        safe=_safe_name(original)
        path=folder/(f"{seq:03d}__"+safe)
        temp=folder/("."+uuid.uuid4().hex+".download")
        count=0
        digest=sha256()
        prefix=b""
        try:
            with temp.open("wb") as handle:
                while True:
                    chunk=response.read(1024*1024)
                    if not chunk:break
                    if count==0:
                        prefix=chunk[:40].lstrip().lower()
                        if prefix.startswith((b"<!doctype",b"<html",b'{"error"',b'{"errormsg"')):
                            raise InventoryError("OFFICIAL_DOWNLOAD_RETURNED_HTML_OR_JSON")
                    count+=len(chunk)
                    if count>MAX_FILE_BYTES or total_before+count>MAX_COLLECTION_BYTES:
                        raise InventoryError("OFFICIAL_ATTACHMENT_EXCEEDS_STORAGE_LIMIT")
                    handle.write(chunk)
                    digest.update(chunk)
            if count==0:raise InventoryError("OFFICIAL_DOWNLOAD_EMPTY_FILE")
            if declared and declared!=count:raise InventoryError("OFFICIAL_ATTACHMENT_LENGTH_MISMATCH")
            os.replace(temp,path)
        finally:
            temp.unlink(missing_ok=True)
        return {
            "file_seq":seq,
            "original_filename":original,
            "filename_from_official_header":has_filename,
            "file_type":_kind(original,prefix,response.headers.get("Content-Type")),
            "content_type":response.headers.get("Content-Type",""),
            "size_bytes":count,
            "sha256":digest.hexdigest(),
            "saved_path":str(path),
            "saved":True,
            "source":url,
            "http_status":200,
            "source_file_sha256":digest.hexdigest(),
        }

def collect(opener,notice):
    """Save only original files; return a manifest for all later evaluation stages."""
    no,order,bsne=_ident(notice)
    folder=STORAGE_ROOT/(no+"-"+order)/"attachments"
    folder.mkdir(parents=True,exist_ok=True)
    files=[]
    errors=[]
    gaps=[]
    misses=[]
    end_confirmed=False
    total=0
    for seq in range(1,MAX_FILES+1):
        try:
            file=_download_one(opener,no,order,bsne,seq,folder,total)
            if file.get("not_found"):
                misses.append(seq)
                if len(misses)>=END_MISSING_RUN and files:
                    end_confirmed=True
                    break
                continue
            if misses:
                gaps.extend(misses)
                misses=[]
            files.append(file)
            total+=file["size_bytes"]
        except Exception as exc:
            errors.append({"file_seq":seq,"error":type(exc).__name__+":"+str(exc)[:170]})
            # A genuine server/network error is NOT a missing file.
            break
    complete=bool(files and end_confirmed and not errors and not gaps
                  and all(f["filename_from_official_header"] for f in files))
    report={
        "source":"official_g2b_bid_notice_attachment_download",
        "source_endpoint":DOWNLOAD,
        "inventory_method":"fileSeq_full_scan_until_3_consecutive_official_HTTP_422",
        "inventory_scope":"PNPE_NOTICE_ATTACHMENT_DOWNLOAD_ENDPOINT",
        "official_attachment_inventory_complete":complete,
        "filename_from_official_header":all(f["filename_from_official_header"] for f in files),
        "notice_bid_no":no,"notice_bid_ord":order,"business_code":bsne,
        "storage_folder":str(folder),
        "file_count":len(files),
        "downloaded":len(files),
        "total_bytes":total,
        "files":files,
        "file_names":[f["original_filename"] for f in files],
        "file_types":[f["file_type"] for f in files],
        "errors":errors,
        "unexpected_missing_indices":gaps,
        "end_of_sequence_confirmed":end_confirmed,
        "last_checked_sequence":seq,
        "enumeration_limit":MAX_FILES,
        "collected_at":_now(),
        "analysis_performed":False,
        "next_stage_payload":"manifest_path_and_original_file_paths",
        "limitations":"Only PNPE notice attachment download files; any separate external RFP/document tab requires its own inventory",
    }
    manifest=folder.parent/"attachment_manifest.json"
    report["manifest_path"]=str(manifest)
    _manifest_save(manifest,report)
    return report

def read_manifest(path,notice=None):
    """Verified handoff: only read manifests rooted in this collector's volume."""
    resolved=Path(path).resolve()
    root=STORAGE_ROOT.resolve()
    if root not in resolved.parents:
        raise ValueError("N02_MANIFEST_OUTSIDE_STORAGE")
    data=json.loads(resolved.read_text(encoding="utf-8"))
    if notice:
        no,order,_=_ident(notice)
        if (data.get("notice_bid_no"),data.get("notice_bid_ord"))!=(no,order):
            raise ValueError("N02_MANIFEST_NOTICE_MISMATCH")
    return data


def verify_saved_files(report):
    """Read back all originals from persistent storage for downstream handoff.

    This is a binary integrity check, NOT document content evaluation.
    """
    if not isinstance(report,dict) or not report.get("manifest_path"):
        raise ValueError("N02_MANIFEST_NOT_AVAILABLE_FOR_HANDOFF")
    source={"bid_no":report["notice_bid_no"],"bid_ord":report["notice_bid_ord"],
            "business_code":report["business_code"]}
    saved=read_manifest(report["manifest_path"],source)
    all_files=saved.get("files") or []
    folder=Path(saved["storage_folder"]).resolve()
    if not all_files or folder!=Path(report["storage_folder"]).resolve():
        raise ValueError("N02_MANIFEST_EMPTY_OR_FOLDER_MISMATCH")
    for f in all_files:
        path=Path(f["saved_path"]).resolve()
        if folder!=path.parent or not path.is_file():
            raise ValueError("N02_SAVED_FILE_MISSING_OR_WRONG_FOLDER")
        if path.stat().st_size!=f["size_bytes"]:
            raise ValueError("N02_SAVED_FILE_BYTES_MISMATCH")
        digest=sha256()
        with path.open("rb") as source_file:
            for buf in iter(lambda:source_file.read(1024*1024),b""):
                digest.update(buf)
        if digest.hexdigest()!=f["sha256"]:
            raise ValueError("N02_SAVED_FILE_SHA256_MISMATCH")
    return {
      "manifest_path":str(Path(report["manifest_path"])),
      "file_count":len(all_files),
      "verified_saved_original_count":len(all_files),
      "original_files_integrity_verified":True,
      "content_analysis_performed":False,
    }
