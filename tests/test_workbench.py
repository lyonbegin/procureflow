"""ProcureFlow real-tender workbench status contracts."""
from datetime import datetime
from zoneinfo import ZoneInfo
from workbench import eligible,_state,_stage,_preview_row,STAGE_CATALOG

def fixture(source="kapt",eid="20261020165014951",deadline="2027-12-31 17:00:00"):
    return {"source":source,"external_id":eid,"category":"일반용역",
            "title":"[서울] 경비용역 재공고","agency":"보문센트럴아이파크아파트",
            "deadline":deadline,"notice_date":"2026-10-20 16:51:00",
            "status":"신규공고","method":"적격심사","source_url":"https://www.k-apt.go.kr/bid/bidList.do",
            "last_seen":datetime.now(ZoneInfo("Asia/Seoul"))}

def test_only_true_notices_can_be_in_workbench():
    assert eligible(fixture())
    assert eligible(fixture("kapt","kg2b_142330"))
    assert eligible(fixture("g2b","R26BK01234567"))
    assert not eligible(fixture("g2b","R26DD20902084"))
    assert not eligible(fixture("g2b","R26XX01234567"))
    x=fixture()
    x["category"]="공사"
    assert not eligible(x)

def test_deadline_is_not_receipt():
    t=fixture(deadline="2020-10-24 17:00:00")
    assert _state(t)=="closed"
    assert _state(t,submitted=True)=="submitted"
    assert _state(fixture())=="unstarted"
    assert _state(fixture(),c={"state":"collecting"})=="collecting"
    assert _state(fixture(),c={"state":"paused"})=="paused"
    assert _state(fixture(),ready=True)=="ai_ready"

def test_draft_is_never_final_offer():
    x=_preview_row(fixture(),None,None,[])
    assert x["work_state"]=="unstarted"
    assert x["proposal_status"]=="검토 초안만 있음"
    assert x["evidence_verified"]==1
    assert not x["submission_verified"]
    assert x["evidence_total"]==len(STAGE_CATALOG)==16

def test_image_capture_not_file_download():
    t=fixture()
    capture={"id":200,"state":"completed","has_detail":True}
    row=_preview_row(t,{"state":"collecting"},capture,[])
    assert row["work_state"]=="collecting"
    assert row["evidence_verified"]==2
    assert row["capture_job"]==200
    assert row["proposal_status"]!="최종본 검증됨"

def test_evidence_requires_provenance_and_checksum():
    t=fixture()
    rows=[{"kind":"final_proposal","record_id":"1","state":"verified",
           "source_uri":"", "sha256":""}]
    assert _preview_row(t,None,None,rows)["proposal_status"]!="최종본 검증됨"
    good=[{"kind":"final_proposal","record_id":"1","state":"verified",
           "source_uri":"https://files.example.org/offer.pdf","sha256":"a"*64}]
    result=_preview_row(t,None,None,good)
    assert result["proposal_status"]=="최종본 검증됨"
    assert result["work_state"]=="proposal_complete"

def test_stage_states_are_explicit():
    assert _stage("attachment_files")["status"]=="missing"
    assert _stage("attachment_files","verified")["status"]=="verified"
