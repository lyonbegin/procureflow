"""Read-only, leakage-aware G2B competitor similarity backtest on existing PostgreSQL rows.

No bid submission, no invented item codes, no use of ingestion timestamps as
auction dates, and no train/test leakage across opening dates.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime
from functools import lru_cache
import math
import re
import unicodedata

from db import session

STOPWORDS=frozenset("입찰 공고 재공고 용역 물품 구매 사업 선정 업체 공사 전자 공개 긴급 일반 제한 조달 제안".split())
SCHEMA_VERSION="g2b-similarity-backtest-v1.0"

def _norm(value):
    return re.sub(r"\s+","",unicodedata.normalize("NFKC",str(value or "")).lower()).strip()

def _category(value):
    x=str(value or "").strip()
    if x in ("goods","물품","01","조070001"):return "goods"
    if x in ("service","일반용역","03","조070002"):return "service"
    return ""

def _auction_time(value):
    """ONLY observed opening time from an original official response."""
    v=str(value or "").strip()
    digits=re.sub(r"\D","",v)
    for pat in ("%Y%m%d%H%M%S","%Y%m%d%H%M","%Y%m%d"):
        if len(digits)==len(datetime.now().strftime(pat)):
            try:return datetime.strptime(digits,pat)
            except ValueError:pass
    if len(digits)>=14:
        try:return datetime.strptime(digits[:14],"%Y%m%d%H%M%S")
        except ValueError:pass
    return None

@lru_cache(maxsize=12000)
def _bigrams(t):
    s=_norm(t)
    return frozenset(s[i:i+2] for i in range(len(s)-1)) if len(s)>1 else frozenset()

@lru_cache(maxsize=12000)
def _words(t):
    parts=re.findall(r"[가-힣A-Za-z0-9]{2,}",unicodedata.normalize("NFKC",str(t or "")).lower())
    return frozenset(x for x in parts if x not in STOPWORDS)

def _jaccard(a,b):
    if not a or not b:return 0.0
    return len(a&b)/len(a|b)

def _family_key(row):
    return "|".join(str(row.get(k) or "").strip() for k in ("bid_ntce_no","bid_ntce_ord","bid_clsfc_no","rbid_no"))

def _build_cases(rows):
    groups={}
    ids_by_notice=defaultdict(list)
    malformed=0
    category_raw=Counter()
    for row in rows:
        no=str(row.get("bid_ntce_no") or "")
        if not no.startswith("R") or "BK" not in no:
            malformed+=1
            continue
        key=_family_key(row)
        g=groups.get(key)
        if g is None:
            g={"key":key,"no":no,"ord":str(row.get("bid_ntce_ord") or ""),
               "title":"","agency":"","category":"","date":None,
               "bidders":set(),"offers":0,"awards":0,"winner":set(),
               "has_status":False,"status_raw":False,"with_business_no":0}
            groups[key]=g
            ids_by_notice[(no,g["ord"])].append(key)
        title=str(row.get("title") or "")
        agency=str(row.get("agency") or "")
        if len(title)>len(g["title"]):g["title"]=title
        if len(agency)>len(g["agency"]):g["agency"]=agency
        raw=row.get("raw") or {}
        if not isinstance(raw,dict):raw={}
        original_category=str(row.get("category") or "")
        category_raw[original_category or "empty"]+=1
        category=_category(original_category)
        if not category:
            listing=raw.get("listing") or {}
            if isinstance(listing,dict):
                category=_category(listing.get("prcmBsneSeCd"))
        if category:g["category"]=category
        kind=row.get("result_kind")
        if kind=="opening_status":
            g["has_status"]=True
            listing=raw.get("listing") or {}
            if isinstance(listing,dict):
                if listing.get("onbsPrnmntDt"):g["status_raw"]=True
                date=_auction_time(listing.get("onbsPrnmntDt"))
                if date and (g["date"] is None or date<g["date"]):g["date"]=date
        elif kind=="opening":
            name=str(row.get("company") or "").strip()
            if name:
                g["bidders"].add(_norm(name))
                g["offers"]+=1
                g["with_business_no"]+=bool(raw.get("bidder_business_no"))
        elif kind=="award":
            g["awards"]+=1
            name=str(row.get("company") or "").strip()
            if name:g["winner"].add(_norm(name))
    # Reconcile details and opening-status rows where the classification
    # and rebid suffix differ but the notice number/order uniquely identify
    # one publicly observed opening date. Never infer time from row insertion.
    for keys in ids_by_notice.values():
        dated={groups[k]["date"] for k in keys if groups[k]["date"] is not None}
        classes={groups[k]["category"] for k in keys if groups[k]["category"]}
        if len(dated)==1:
            dt=next(iter(dated))
            for k in keys:
                if groups[k]["date"] is None:groups[k]["date"]=dt
        if len(classes)==1:
            cat=next(iter(classes))
            for k in keys:
                if not groups[k]["category"]:groups[k]["category"]=cat
    return list(groups.values()),{"invalid_rows":malformed,"stored_category_rows":dict(category_raw)}

def _score(target,history):
    if target["category"] and history["category"] and target["category"]!=history["category"]:
        return None
    title=_jaccard(_bigrams(target["title"]),_bigrams(history["title"]))
    token=_jaccard(_words(target["title"]),_words(history["title"]))
    same_agency=bool(_norm(target["agency"]) and _norm(target["agency"])==_norm(history["agency"]))
    same_category=bool(target["category"] and target["category"]==history["category"])
    delta=max(0,(target["date"]-history["date"]).days)
    age=math.exp(-math.log(2)*delta/365)
    score=45*title+20*same_agency+15*same_category+10*token+10*age
    relevant=(same_agency or title>=0.18 or token>=0.20)
    return round(score,6) if relevant else None

def _predict(target,training,limit=10):
    nearby=[]
    for old in training:
        score=_score(target,old)
        if score is not None:nearby.append((score,old))
    nearby.sort(key=lambda x:(-x[0],x[1]["key"]))
    nearby=nearby[:25]
    combined=Counter()
    for weight,g in nearby:
        for bidder in g["bidders"]:combined[bidder]+=weight/100
    ranked=[name for name,_ in sorted(combined.items(),key=lambda x:(-x[1],x[0]))[:limit]]
    return ranked,{"similar_executions":len(nearby),
                   "highest_similarity_score":nearby[0][0] if nearby else 0,
                   "candidate_companies":len(combined)}

def _baseline(training,limit=10):
    c=Counter()
    for g in training:
        for bidder in g["bidders"]:c[bidder]+=1
    return [x for x,_ in sorted(c.items(),key=lambda x:(-x[1],x[0]))[:limit]]

def _measure(pred,actual,k):
    arr=pred[:k]
    found=len(actual.intersection(arr))
    return {"hits":found,"any_hit":int(found>0),
            "recall":found/len(actual) if actual else 0,
            "precision":found/k}

def backtest(rows):
    groups,aux=_build_cases(rows)
    with_bidders=[g for g in groups if g["bidders"]]
    dated=sorted([g for g in with_bidders if g["date"]],
                 key=lambda g:(g["date"],g["key"]))
    counts=Counter(g["category"] or "unspecified" for g in groups)
    no_date=len(with_bidders)-len(dated)
    all_firms=Counter(name for g in with_bidders for name in g["bidders"])
    repeat=sum(1 for v in all_firms.values() if v>=2)
    def bidder_bands(items):
        return {"single_bidder":sum(len(g["bidders"])==1 for g in items),
                "two_to_four":sum(2<=len(g["bidders"])<=4 for g in items),
                "five_to_nineteen":sum(5<=len(g["bidders"])<20 for g in items),
                "twenty_plus":sum(len(g["bidders"])>=20 for g in items)}
    coverage={
        "raw_rows":len(rows),"executions":len(groups),
        "executions_with_bidders":len(with_bidders),
        "with_official_opening_date":len(dated),
        "no_official_opening_date":no_date,
        "date_coverage_of_bidder_executions":round(len(dated)/len(with_bidders),4) if with_bidders else 0,
        "categories":dict(counts),
        "distinct_bidder_names":len(all_firms),
        "repeat_bidder_names_2plus":repeat,
        "repeat_bidder_fraction":round(repeat/len(all_firms),4) if all_firms else 0,
        "bidder_distribution":bidder_bands(with_bidders),
        "dated_bidder_distribution":bidder_bands(dated),
        "opening_date_range":{
            "min":dated[0]["date"].isoformat() if dated else None,
            "max":dated[-1]["date"].isoformat() if dated else None},
        "bidder_offers":sum(g["offers"] for g in groups),
        "offers_with_business_no":sum(g["with_business_no"] for g in groups),
        "observed_award_rows":sum(g["awards"] for g in groups),
        "field_coverage":{
            "title":sum(bool(g["title"]) for g in groups),
            "agency_name":sum(bool(g["agency"]) for g in groups),
            "known_category":sum(bool(g["category"]) for g in groups),
            "real_opening_date":sum(bool(g["date"]) for g in groups),
            "standard_item_code":0,
            "agency_code":0,
            "bid_method_code":0,
            "base_amount":0,
            "eligibility_regions":0,
            "license_restrictions":0
        },
        "category_rows_before_recovery":aux["stored_category_rows"]
    }
    output={"status":"insufficient_temporal_coverage",
            "schema_version":SCHEMA_VERSION,
            "source":"procureflow.bid_results (live PostgreSQL)",
            "coverage":coverage,
            "protocol":{
                "unit":"unique bid_no/ord/clsfc/rebid execution",
                "time":"official onbsPrnmntDt only; NEVER last_seen or notice-number chronology",
                "split":"chronological last 30%, strictly older observations only",
                "features":"prebid-proxy title, agency name, goods/service; no invented item or agency codes",
                "target":"observed bidder names, not final winners; company identity by normalized name",
                "models":["similarity_top25","historical_bidder_frequency_baseline"],
                "metrics":["hit_at_5","recall_at_5","hit_at_10","recall_at_10","precision_at_10"],
                "scope":"retrospective feasibility proxy; not prospective out-of-time production performance"
            },
            "results":{},"samples":[]}
    if len(dated)<12:
        output["reason"]="fewer_than_12_executions_with_verified_opening_date_and_bidders"
        return output
    border=max(9,int(len(dated)*0.70))
    if border>=len(dated)-2:
        output["reason"]="insufficient_holdout"
        return output
    evals=dated[border:]
    matrix=defaultdict(lambda:defaultdict(float))
    counts_eval=defaultdict(int)
    samples=[]
    by_segment=defaultdict(lambda:{"n":0,"similarity_any_hit":0,"baseline_any_hit":0,
                                   "similarity_recall_sum":0.0,"baseline_recall_sum":0.0})
    for target in evals:
        older=[g for g in dated if g["date"]<target["date"]]
        if len(older)<9:continue
        model,features=_predict(target,older)
        baseline=_baseline(older)
        true=target["bidders"]
        for label,pred in (("similarity",model),("popularity_baseline",baseline)):
            counts_eval[label]+=1
            matrix[label]["predicted_nonempty"]+=int(bool(pred))
            for k in (5,10):
                metric=_measure(pred,true,k)
                for name,value in metric.items():
                    matrix[label][f"{name}@{k}"]+=value
        v=_measure(model,true,10)
        b=_measure(baseline,true,10)
        segments=[
            "single_bidder" if len(true)==1 else
            "2_to_4_bidders" if len(true)<=4 else
            "5_to_19_bidders" if len(true)<20 else "20plus_bidders",
            "category_known" if target["category"] else "category_unknown",
            "similar_history_present" if features["similar_executions"] else
            "no_similar_history",
            "generic_agency" if _norm(target["agency"]) in
            ("각수요기관","수요기관") else "named_agency"
        ]
        for tag in segments:
            part=by_segment[tag]
            part["n"]+=1
            part["similarity_any_hit"]+=v["any_hit"]
            part["baseline_any_hit"]+=b["any_hit"]
            part["similarity_recall_sum"]+=v["recall"]
            part["baseline_recall_sum"]+=b["recall"]
        if len(samples)<12:
            samples.append({"bid_no":target["no"],"bid_ord":target["ord"],
                "opening_date":target["date"].isoformat(),
                "title":target["title"][:110],
                "agency":target["agency"][:90],
                "category":target["category"] or "unspecified",
                "actual_bidders":len(true),
                "similar_candidate_executions":features["similar_executions"],
                "similar_candidate_companies":features["candidate_companies"],
                "model_hits_at_10":v["hits"],
                "baseline_hits_at_10":b["hits"]})
    n=counts_eval["similarity"]
    if not n:
        output["reason"]="no_strictly_prior_training_executions"
        return output
    results={}
    for label in ("similarity","popularity_baseline"):
        c=matrix[label]
        results[label]={
            "evaluated_executions":counts_eval[label],
            "prediction_coverage":round(c["predicted_nonempty"]/n,4),
            "hit_at_5":round(c["any_hit@5"]/n,4),
            "hit_at_10":round(c["any_hit@10"]/n,4),
            "mean_recall_at_5":round(c["recall@5"]/n,4),
            "mean_recall_at_10":round(c["recall@10"]/n,4),
            "mean_precision_at_10":round(c["precision@10"]/n,4),
            "total_correct_top10":int(c["hits@10"])
        }
    output["status"]="completed"
    output["holdout_cutoff_opening_date"]=dated[border]["date"].isoformat()
    output["train_count_at_split"]=border
    output["holdout_total"]=len(evals)
    output["results"]=results
    output["samples"]=samples
    output["segments"]={
       name:{"evaluated":part["n"],
             "model_hit_at_10":round(part["similarity_any_hit"]/part["n"],4),
             "baseline_hit_at_10":round(part["baseline_any_hit"]/part["n"],4),
             "model_mean_recall_at_10":round(part["similarity_recall_sum"]/part["n"],4),
             "baseline_mean_recall_at_10":round(part["baseline_recall_sum"]/part["n"],4)}
       for name,part in sorted(by_segment.items()) if part["n"]
    }
    output["diagnosis"]={
        "delta_hit_at_10":round(results["similarity"]["hit_at_10"]-
                                results["popularity_baseline"]["hit_at_10"],4),
        "delta_recall_at_10":round(results["similarity"]["mean_recall_at_10"]-
                                   results["popularity_baseline"]["mean_recall_at_10"],4),
        "is_similarity_better_at_recall_10":
            results["similarity"]["mean_recall_at_10"]>
            results["popularity_baseline"]["mean_recall_at_10"],
        "not_yet_tested":["standard_item_codes","agency_codes","eligibility_restrictions",
                          "price_similarity","actual_final_winner_prediction"]
    }
    return output

def run_postgres_backtest():
    # All rows: opening-status attaches dated public list evidence to the same
    # execution as opening bidder rows. No crawler, writes or other sources.
    with session() as con:
        rows=con.execute("""SELECT bid_ntce_no,bid_ntce_ord,bid_clsfc_no,rbid_no,
                    title,agency,category,result_kind,company,amount,rank,
                    raw FROM procureflow.bid_results
                    WHERE source='g2b' AND result_kind IN
                    ('opening','opening_status','award')
                    ORDER BY bid_ntce_no,bid_ntce_ord,bid_clsfc_no,rbid_no
                """).fetchall()
    return backtest(rows)


def analyze_one_historical_bid(bid_no, bid_ord="000"):
    """Inspect a single recorded opening using only earlier comparable openings.

    Returns the actual neighboring historical bid IDs and bidder candidates.
    Read-only. Not a live-bid estimator when no current G2B notice is stored.
    """
    if not re.fullmatch(r"R\d{2}BK\d{8}",bid_no or ""):
        raise ValueError("official R..BK bid number required")
    if not re.fullmatch(r"\d{3}",bid_ord or ""):
        raise ValueError("3-digit bid order required")
    with session() as con:
        rows=con.execute("""SELECT bid_ntce_no,bid_ntce_ord,bid_clsfc_no,rbid_no,
                           title,agency,category,result_kind,company,amount,rank,raw
                           FROM procureflow.bid_results
                           WHERE source='g2b' AND result_kind IN
                           ('opening','opening_status','award')
                        """).fetchall()
    groups,_=_build_cases(rows)
    matching=[g for g in groups if g["no"]==bid_no and g["ord"]==bid_ord
              and g["date"] and g["bidders"]]
    if not matching:
        raise LookupError("no recorded opening date and bidders for this execution")
    target=sorted(matching,key=lambda g:(g["date"],g["key"]))[0]
    older=[g for g in groups if g["date"] and g["date"]<target["date"] and g["bidders"]]
    candidate_scores=sorted(
        [(score,g) for g in older
         if (score:=_score(target,g)) is not None],
        key=lambda z:(-z[0],z[1]["key"]))[:25]
    company_weights=Counter()
    for score,g in candidate_scores:
        for bidder in g["bidders"]:company_weights[bidder]+=score/100
    predictions=sorted(company_weights.items(),key=lambda z:(-z[1],z[0]))[:10]
    return {
        "status":"historical_as_of_opening_date",
        "not_a_current_tender":True,
        "source":"real_procureflow_postgresql",
        "bid_no":target["no"],"bid_ord":target["ord"],
        "opening_at":target["date"].isoformat(),
        "title":target["title"],"agency":target["agency"],
        "category":target["category"] or "unspecified",
        "strictly_older_executions":len(older),
        "similar_historical_executions":[
            {"bid_no":g["no"],"bid_ord":g["ord"],"title":g["title"][:160],
             "agency":g["agency"][:90],"category":g["category"] or "unspecified",
             "opening_at":g["date"].isoformat(),
             "similarity_score":round(score,2),
             "observed_bidders":len(g["bidders"])}
            for score,g in candidate_scores[:15]
        ],
        "predicted_bidder_names":[
            {"company":name,"ranking_score":round(score,4),
             "was_actual_participant":name in target["bidders"]}
            for name,score in predictions],
        "actual_bidder_count":len(target["bidders"]),
        "correct_top10":sum(x in target["bidders"] for x,_ in predictions),
        "notes":"Only opening-result bidder names; no item classification code, base amount, or verified bid constraints."
    }
