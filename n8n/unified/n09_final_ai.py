"""N09: the ONLY stage permitted to analyze procurement, assess or draft.

N01–N08 are source collection exclusively. This module performs no analysis
if the AI API credential/model is not explicitly configured. No auto-bidding.
"""
from __future__ import annotations
from hashlib import sha256
from urllib.request import Request,urlopen
import json,os,re

API="https://api.openai.com/v1/responses"
MAX_EVIDENCE_CHARS=105000
MAX_REPLY_BYTES=1_200_000
TOPICS=("participant_eligibility","competition_analysis","cost_review",
        "bid_price_strategy","proposal_outline","submission_requirements",
        "risks_and_gaps","overall_recommendation")
SYSTEM=(
 "당신은 공공조달 입찰 자료의 최종 평가 분석기입니다. N01~N08은 자료 수집만 수행했습니다. "
 "제공받은 실제 공식 공고·문서·이력과 출처만 인용하십시오. 근거가 없으면 반드시 '미확인'으로 표기하십시오. "
 "입찰자격의 최종 법적 판단, 낙찰 보장, 자동 투찰·전자서명·입찰참가를 수행하지 마십시오. "
 "최종 보고서에는 참가자격 대조 필요사항, 예상 경쟁·과거 참가자료, "
 "원가 및 투찰가격 전략의 불확실성, 제출문서 목록, 위험·누락, 사람의 승인 필요사항을 포함하십시오. "
 "모든 금액과 적격 판단은 출처가 없는 경우 추측하지 마십시오."
)
class AIInputError(ValueError):pass

def _texts_from_originals(files,read_original,extract_text):
    """Only N09 touches attachment contents. Preserve extraction gaps."""
    seen=set();parts=[];sources=[];gaps=[];truncated=False
    for file in files:
        seq=file.get("file_seq")
        if not isinstance(seq,int) or seq in seen:raise AIInputError("N09_DUPLICATE_ORIGINAL_SEQUENCE")
        seen.add(seq)
        raw=read_original(file)
        if not isinstance(raw,bytes) or len(raw)!=file.get("size_bytes") or sha256(raw).hexdigest()!=file.get("sha256"):
            raise AIInputError("N09_ORIGINAL_SHA256_MISMATCH")
        item={"file_seq":seq,"original_filename":file.get("original_filename"),
              "original_sha256":file["sha256"],"source":file.get("source")}
        try:
            content,kind=extract_text(raw,file.get("content_type",""))
            if not isinstance(content,str) or not content.strip():
                raise ValueError("NO_EXTRACTABLE_ORIGINAL_TEXT")
            remaining=MAX_EVIDENCE_CHARS-sum(len(p["text"]) for p in parts)
            if remaining<=0:
                truncated=True
                gaps.append("original_text_budget_exceeded:"+str(seq))
            else:
                excerpt=content[:remaining]
                parts.append({**item,"text":excerpt,"format":kind,
                    "source_text_sha256":sha256(content.encode()).hexdigest(),
                    "text_truncated":len(excerpt)<len(content)})
                truncated=truncated or len(excerpt)<len(content)
        except (ValueError,RuntimeError,ImportError,EOFError,TypeError) as exc:
            gaps.append("original_text_extract_failed:"+str(seq)+":"+type(exc).__name__)
        sources.append(item)
    return parts,sources,gaps,truncated

def evaluate(previous,read_original,extract_text,request=None):
    """Call OpenAI Responses API only at N09, never earlier."""
    bundle=(previous.get("N08") or {}).get("handoff_bundle")
    if not isinstance(bundle,dict):
        return "partial",{"source":"N01_N08_handoff",
           "ai_evaluation_performed":False,"reason":"N08_HANDOFF_BUNDLE_MISSING",
           "final_bid_approval":False,"bid_submitted":False}
    originals=bundle.get("originals") or []
    files=(previous.get("N02") or {}).get("files") or []
    if len(originals)!=len(files):
        return "partial",{"source":"N02_N08_handoff",
            "ai_evaluation_performed":False,"reason":"ORIGINAL_MANIFEST_COUNT_MISMATCH",
            "final_bid_approval":False,"bid_submitted":False}
    if {x["sha256"] for x in originals}!={x["sha256"] for x in files}:
        return "partial",{"source":"N02_N08_handoff",
            "ai_evaluation_performed":False,"reason":"ORIGINAL_MANIFEST_SHA256_MISMATCH",
            "final_bid_approval":False,"bid_submitted":False}
    key=os.environ.get("OPENAI_API_KEY","").strip()
    model=os.environ.get("PROCUREFLOW_AI_MODEL","").strip()
    enabled=os.environ.get("PROCUREFLOW_AI_ENABLED","").strip()=="1"
    if not key or not model or not enabled:
        # No model call was made. A missing API credential is NOT partial
        # AI analysis: represent the evaluation as unexecuted, with sources
        # safely preserved and without pretending to have produced a report.
        return "not_executed",{"source":"N01_N08_handoff",
            "ai_evaluation_performed":False,
            "reason":"N09_AI_API_NOT_CONFIGURED",
            "evaluation_state":"not_started_missing_credentials",
            "original_manifest_count":len(files),
            "collection_gaps":bundle.get("collection_gaps",[])[:120],
            "next_required":"Set OPENAI_API_KEY, PROCUREFLOW_AI_MODEL and PROCUREFLOW_AI_ENABLED=1 in GitHub Actions secrets/variables",
            "final_bid_approval":False,"bid_submitted":False}
    text,sources,read_gaps,truncated=_texts_from_originals(
        files,read_original,extract_text)
    # Do not claim complete analysis when source files are not text-extractable.
    scoped={"N01_N08_collection":bundle,
            "original_document_texts":text,
            "original_sources":sources,
            "text_extraction_gaps":read_gaps,
            "text_truncated":truncated,
            "instructions":"원본 출처 파일 순번과 SHA-256을 근거로 사용하고 판단할 수 없는 항목은 미확인으로 표기"}
    model_input=json.dumps(scoped,ensure_ascii=False,separators=(",",":"))
    if len(model_input)>450000:
        raise AIInputError("N09_AI_CONTEXT_TOO_LARGE_NO_SILENT_LOSS")
    request_body={"model":model,"store":False,
        "instructions":SYSTEM,
        "input":[{"role":"user","content":model_input}]}
    call=request or _post_openai
    response=call(request_body,key)
    if not isinstance(response,dict) or response.get("status")!="completed":
        return "partial",{"ai_evaluation_performed":False,
            "reason":"N09_AI_RESPONSE_NOT_COMPLETED",
            "model":model,"final_bid_approval":False,"bid_submitted":False}
    excerpts=[]
    for block in response.get("output") or []:
        if block.get("type")!="message":continue
        for part in block.get("content") or []:
            if part.get("type")=="output_text" and isinstance(part.get("text"),str):
                excerpts.append(part["text"])
    report="\n\n".join(excerpts).strip()
    if len(report)<100:
        return "partial",{"ai_evaluation_performed":False,
            "reason":"N09_AI_RESULT_TEXT_UNAVAILABLE",
            "final_bid_approval":False,"bid_submitted":False}
    result={"source":"OpenAI_Responses_API",
        "model":model,"ai_response_id":response.get("id"),
        "ai_evaluation_performed":True,
        "report_text":report[:120000],
        "report_sha256":sha256(report.encode()).hexdigest(),
        "originals_read":len(files),"originals_with_text":len(text),
        "original_text_truncated":truncated,
        "text_extraction_gaps":read_gaps,
        "collection_gaps":bundle.get("collection_gaps",[])[:120],
        "final_bid_approval":False,"bid_submitted":False,
        "human_review_required":True}
    # A report can be generated while historical evidence remains incomplete.
    # Mark the stage partial unless ALL cited source collection gaps are absent.
    status="verified" if not bundle.get("collection_gaps") and not read_gaps and not truncated else "partial"
    return status,result

def _post_openai(body,key):
    raw=json.dumps(body,ensure_ascii=False).encode()
    request=Request(API,raw,method="POST",headers={
        "Authorization":"Bearer "+key,
        "Content-Type":"application/json",
        "Accept":"application/json",
        "User-Agent":"ProcureFlow-GitHub-Only-N09"})
    with urlopen(request,timeout=120) as response:
        content=response.read(MAX_REPLY_BYTES+1)
        if len(content)>MAX_REPLY_BYTES:raise AIInputError("N09_AI_REPLY_TOO_LARGE")
        return json.loads(content)
