"""Validated, persisted K-apt public-bid filters. No private API, no fabricated site codes."""
from __future__ import annotations
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

TZ = timezone(timedelta(hours=9))
KIND_CODES = {'goods': ('04','물품'), 'service': ('03','일반용역'), 'construction':('02','공사'), 'other':('05','기타')}
CHOICES = {
    'searchBidGb': ('bid_gb_1','bid_gb_2'),
    'searchDateGb': ('reg','bid'),
    'dateArea': ('1','2','3','4'),
    'bidState': ('','1','2','3','100'),
    'codeAuth': ('','01','02','04,05,03,06,07,08,09,10'),
    'codeWay': ('','00','01'),
    'codeAuthSub': ('','04','05','03','06','07','08','09','10'),
    'codeSucWay': ('','02','03','04'),
    'codeClassifyType1': ('','01','02'),
}
DEFAULTS = {
    'searchBidGb': 'bid_gb_1','bidTitle':'','aptName':'','searchDateGb':'reg',
    'dateStart':'','dateEnd':'','dateArea':'1', 'bidState':'','codeAuth':'',
    'codeWay':'','codeAuthSub':'','codeSucWay':'','codeClassifyType1':'02',
    'categories':['goods','service'],
    'subtypes': {'goods':'13','service':'','construction':'','other':''},
    'pageSelect':100, 'dateRolling':True,
}

def _rolling_dates(date_area):
    today=datetime.now(TZ).date()
    start=today-timedelta(days={'1':30,'2':90,'3':180,'4':365}[date_area])
    return start.isoformat(),today.isoformat()

def default_config():
    d=json.loads(json.dumps(DEFAULTS))
    d['dateStart'],d['dateEnd']=_rolling_dates(d['dateArea'])
    return d

def validate_filters(payload):
    if payload is None: return default_config()
    if not isinstance(payload,dict): raise ValueError('검색조건은 JSON 객체여야 합니다.')
    unknown=set(payload)-set(DEFAULTS)
    if unknown:raise ValueError('알 수 없는 검색조건: '+', '.join(sorted(unknown)))
    result=default_config()
    for k,v in payload.items():
        if k not in ('categories','subtypes'):result[k]=v
    for k,choices in CHOICES.items():
        val=result[k]
        if not isinstance(val,str) or val not in choices:raise ValueError(f'{k}: 허용되지 않은 값입니다: {val!r}')
    if type(result['dateRolling']) is not bool:raise ValueError('자동 날짜갱신은 참/거짓이어야 합니다.')
    if result['dateRolling']:
        result['dateStart'],result['dateEnd']=_rolling_dates(result['dateArea'])
    for k in ('bidTitle','aptName'):
        if not isinstance(result[k],str) or len(result[k])>120:raise ValueError(f'{k}: 120자 이내로 입력하십시오.')
        result[k]=result[k].strip()
    for k in ('dateStart','dateEnd'):
        val=result[k]
        if not isinstance(val,str):raise ValueError(f'{k}: YYYY-MM-DD 형식이 아닙니다.')
        try:datetime.strptime(val,'%Y-%m-%d')
        except ValueError:raise ValueError(f'{k}: YYYY-MM-DD 형식으로 입력하십시오.')
    if result['dateStart']>result['dateEnd']:raise ValueError('시작일이 종료일보다 늦습니다.')
    size=result['pageSelect']
    if type(size)!=int or size not in (10,30,50,100):raise ValueError('페이지당 건수는 10·30·50·100 중 선택하십시오.')
    cats=payload.get('categories',result['categories'])
    if not isinstance(cats,list) or not cats or len(set(map(str,cats)))!=len(cats) or any(k not in KIND_CODES for k in cats):
        raise ValueError('입찰분류2는 물품·용역·공사·기타 중 하나 이상 선택하십시오.')
    result['categories']=list(cats)
    subs=payload.get('subtypes',result['subtypes'])
    if not isinstance(subs,dict) or any(k not in KIND_CODES for k in subs):raise ValueError('입찰분류3 설정이 잘못되었습니다.')
    result['subtypes']={**result['subtypes'],**subs}
    for k,v in result['subtypes'].items():
        if not isinstance(v,str) or (v and not re.fullmatch(r'[0-9A-Za-z_]{1,12}',v)):
            raise ValueError(f'{k} 하위분류는 실제 사이트의 코드만 입력하십시오.')
    # CodeAuthSub only applies when private operators selected; avoid bogus cross-filters.
    if result['codeAuth']!='04,05,03,06,07,08,09,10' and result['codeAuthSub']:
        raise ValueError('민간운영사를 지정하려면 입찰기관을 민간운영으로 선택하십시오.')
    return result

def build_url(base,kind,page_no=1,config=None):
    c=validate_filters(config)
    if kind not in c['categories']:raise ValueError(f'{kind}: 선택하지 않은 분류입니다.')
    if type(page_no)!=int or page_no<1 or page_no>10000:raise ValueError('페이지 번호가 올바르지 않습니다.')
    from time import time
    category_code,_=KIND_CODES[kind]
    params={
      'pageSelect':str(c['pageSelect']),
      'searchBidGb':c['searchBidGb'], 'bidTitle':c['bidTitle'],'aptName':c['aptName'],
      'searchDateGb':c['searchDateGb'],'dateStart':c['dateStart'],'dateEnd':c['dateEnd'],
      'dateArea':c['dateArea'], 'bidState':c['bidState'],'codeAuth':c['codeAuth'],
      'codeWay':c['codeWay'],'codeAuthSub':c['codeAuthSub'],'codeSucWay':c['codeSucWay'],
      'codeClassifyType1':c['codeClassifyType1'],
      'codeClassifyType2':category_code,
      'codeClassifyType3':c['subtypes'].get(kind,''),
      'pageNo':str(page_no),'type':'4','bidArea':'','bidNum':'','bidNo':'',
      'dTime':str(int(time()*1000)),'mainKaptCode':'','aptCode':'',
    }
    return base+'?'+urlencode(params)

def init_config_db(con):
    con.execute('''CREATE TABLE IF NOT EXISTS kapt_search_settings(
      id INTEGER PRIMARY KEY CHECK(id=1), config_json TEXT NOT NULL,updated_at TEXT NOT NULL)''')

def load_config(con):
    init_config_db(con)
    row=con.execute('SELECT config_json FROM kapt_search_settings WHERE id=1').fetchone()
    if row is None:return default_config()
    return validate_filters(json.loads(row[0]))

def save_config(con,payload):
    cfg=validate_filters(payload)
    init_config_db(con)
    at=datetime.now(TZ).isoformat(timespec='seconds')
    con.execute('''INSERT INTO kapt_search_settings(id,config_json,updated_at)
        VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET config_json=excluded.config_json,
        updated_at=excluded.updated_at''',(json.dumps(cfg,ensure_ascii=False),at))
    con.commit()
    return cfg
