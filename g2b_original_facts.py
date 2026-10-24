"""Extract source-cited constraints from the actual G2B PDF/HWP originals."""
import re
from db import session
from g2b_case_engine import SINGLE_CASE,_ev
def _flat(text):
    return " ".join((text or "").split())

def run():
    with session() as db:
        docs=db.execute("""SELECT file_id,filename,url,sha256,extracted_text,
                      extraction_state,source_verified
                      FROM procureflow.g2b_case_documents
                      WHERE bid_no=%s ORDER BY file_id""",(SINGLE_CASE,)).fetchall()
    result={"notice":SINGLE_CASE,"original_documents_checked":len(docs),
            "readable_documents":0,"facts":[]}
    for doc in docs:
        if not doc["source_verified"] or doc["extraction_state"]!="parsed":
            continue
        text=_flat(doc["extracted_text"])
        if len(text)<100:continue
        result["readable_documents"]+=1
        proofs=[]
        def capture(kind,pattern,field=None):
            m=re.search(pattern,text,re.I)
            if m:
                value=m.group(1) if m.lastindex else m.group(0)
                snippet=text[max(0,m.start()-70):m.end()+95]
                proof={"kind":kind,"value":value,"snippet":snippet,
                       "filename":doc["filename"],"source_sha":doc["sha256"]}
                proofs.append(proof)
                return value
            return None
        reg=capture("industry_codes",r"소프트웨어사업자.{0,85}?업종코드\s*[:：]?\s*(1468)")
        code=capture("requirements",r"(8111159901)")
        budget=capture("verified_base_amount",r"기초\s*금액\s*[:：]?\s*([\d,]{7,})\s*원")
        region=capture("region_codes",r"본점.{0,150}?(전라남도)")
        period=capture("contract_terms",r"계약체결일로부터\s*(\d+)\s*일")
        estimated=capture("estimated_amount",r"추정가격\s*[:：]?\s*([\d,]{6,})")
        vat=capture("vat_amount",r"부가가치세\s*[:：]?\s*([\d,]{5,})")
        method=capture("contract_method",r"(소액\s*수의\s*전자견적서\s*제출|수의견적\s*제출\s*방식)")
        small=capture("company_restrictions",r"(소기업.{0,140}?소상공인확인서)")
        floor=capture("price_rules",r"낙찰\s*하한율?\s*[:：]?\s*(88(?:\.0+)?)\s*%")
        if not proofs:continue
        with session() as db:
            for proof in proofs:
                data={"field":proof["kind"],"value":proof["value"],
                      "quoted_context":proof["snippet"],
                      "document_sha":proof["source_sha"],
                      "filename":proof["filename"]}
                _ev(db,SINGLE_CASE,proof["kind"],"original_"+doc["file_id"],
                    True,"정부 원본 첨부문서에서 규칙으로 추출",
                    doc["url"],data)
        result["facts"].extend(proofs)
    result["status"]="parsed" if result["facts"] else "no_rules_extracted"
    result["eligible_company_verified"]=False
    return result
