"""N03 documented eligibility requirements from N02 original source files.

Only GitHub Actions executes this module; Railway stores verified binary files.
No company records, historical DB rows, guesses or bidder eligibility approval.
"""
from __future__ import annotations

from hashlib import sha256
from typing import Callable
import re
from n03_eligibility import analyze

MAX_ORIGINAL_SIZE=96*1024*1024
MAX_RESULT_TEXT=10000

class N03SourceError(ValueError):
    pass

def extract_requirements(files,originals,extract_text:Callable):
    """Evidence-linked parse of all officially downloaded originals.

    Args:
      files: N02 original source file manifest (source URL, seq, SHA-256).
      originals: mapping seq -> bytes, downloaded *again* from persistent Railway
                 storage by a GitHub runner using authenticated read-only route.
      extract_text: existing magic-byte extractor (HWP5, PDF, HWPX, DOCX).

    Returns: (stage_status, N03 output). A requirement extract may succeed while
             the bidder's actual qualification remains unverified (partial).
    """
    if not isinstance(files,list) or not files:
        return "blocked",{"source":"N02_original_manifest",
                          "reason":"N03_NO_OFFICIAL_ORIGINALS",
                          "document_requirement_extraction":"not_verified",
                          "company_eligibility":"NOT_VERIFIED_NO_COMPANY_ORIGINAL",
                          "company_eligibility_verified":False,
                          "analysis_performed":False,"source_files":[]}
    if len(files)>64:raise N03SourceError("N03_TOO_MANY_FILES")
    parsed=[]
    texts=[]
    coverage=[]
    issues=[]
    processed=set()
    total=0
    for file in files:
        if not isinstance(file,dict):
            raise N03SourceError("N03_SOURCE_FILE_MANIFEST_INVALID")
        seq=file.get("file_seq")
        if not isinstance(seq,int) or not 1<=seq<=64 or seq in processed:
            raise N03SourceError("N03_SOURCE_FILE_SEQUENCE_INVALID")
        processed.add(seq)
        checksum=str(file.get("sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}",checksum):
            raise N03SourceError("N03_SOURCE_SHA256_MISSING")
        declared=file.get("size_bytes")
        if not isinstance(declared,int) or not 0<declared<=MAX_ORIGINAL_SIZE:
            raise N03SourceError("N03_ORIGINAL_SIZE_INVALID")
        raw=originals.get(seq)
        if not isinstance(raw,bytes) or not raw:
            raise N03SourceError("N03_OFFICIAL_ORIGINAL_NOT_RECEIVED")
        if len(raw)!=declared or sha256(raw).hexdigest()!=checksum:
            raise N03SourceError("N03_OFFICIAL_ORIGINAL_INTEGRITY_FAILED")
        total+=len(raw)
        filename=str(file.get("original_filename") or f"첨부_{seq:03d}")[:180]
        entry={"file_seq":seq,"original_filename":filename,
               "sha256":checksum,"size_bytes":len(raw),
               "source":file.get("source"),"original_integrity_verified":True,
               "content_extraction":"not_attempted"}
        try:
            text,kind=extract_text(raw,file.get("content_type",""))
            if not isinstance(text,str) or not text.strip():
                raise ValueError("N03_NO_TEXT_IN_EXTRACTED_ORIGINAL")
            if len(text)>1_500_000:
                text=text[:1_500_000]
                entry["text_truncated"]=True
            entry["content_extraction"]="extracted"
            entry["file_type_detected"]=kind
            entry["text_chars"]=len(text)
            entry["text_sha256"]=sha256(text.encode()).hexdigest()
            parsed.append({**file,"text_chars":len(text),"format":kind})
            texts.append(text)
        except (ValueError,ImportError,RuntimeError,TypeError,EOFError) as e:
            # A non-text attachment is NEVER counted as a successfully
            # analyzed qualification document. We still retain its provenance.
            entry["content_extraction"]="unavailable"
            entry["reason"]=type(e).__name__+":"+str(e)[:100]
            issues.append({"file_seq":seq,"original_filename":filename,
                           "reason":entry["reason"]})
        coverage.append(entry)
    verified_files=sum(x["original_integrity_verified"] for x in coverage)
    if verified_files!=len(files):
        raise N03SourceError("N03_SAVED_ORIGINAL_INTEGRITY_NOT_CONFIRMED")
    if parsed:
        result=analyze(parsed,texts)
    else:
        result={"source":"N02_saved_official_originals",
                "document_requirement_extraction":"not_verified",
                "qualification_rules":[],"required_documents":[],
                "procedural_conditions":[],"bid_deadlines":[],
                "qualification_rule_count":0,"required_document_count":0,
                "source_files":[],"document_text_chars":0,
                "company_eligibility":"NOT_VERIFIED_NO_COMPANY_ORIGINAL",
                "company_eligibility_verified":False,
                "missing_company_evidence":["공고가 요구하는 업체 자격·서류의 원본 증빙"],
                "reason":"N03_NO_TEXTUAL_ORIGINAL_AVAILABLE"}
    # Parsing the official document is NOT verification that the bidder is
    # qualified. Keep stage non-verified until our company's originals exist.
    result.update({
        "source":"official_N02_saved_originals_via_github_actions",
        "N02_original_count":len(files),
        "originals_integrity_verified":True,
        "verified_original_count":verified_files,
        "text_extracted_files":len(parsed),
        "file_inspection":coverage,
        "extraction_issues":issues,
        "downloaded_bytes_reviewed":total,
        "analysis_performed":bool(parsed),
        "company_eligibility":"NOT_VERIFIED_NO_COMPANY_ORIGINAL",
        "company_eligibility_verified":False,
        "final_bid_approval":False,
        "next_required":"Verify bidder company originals against evidenced public notice requirements",
    })
    if result.get("document_requirement_extraction")=="verified":
        return "partial",result
    if parsed:
        return "partial",result
    return "blocked",result
