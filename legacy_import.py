"""Sync original SQLite result rows into isolated Railway PostgreSQL schema."""
import json,sqlite3
from pathlib import Path
from db import session,store

def value(x):return str(x or '')
def g2b_row(row):
    raw=value(row.get('raw_json','{}'))
    try: parsed=json.loads(raw)
    except (ValueError,TypeError):parsed={'raw':raw}
    return dict(source='g2b',external_id=value(row.get('request_no')),
        title=value(row.get('title')),agency=value(row.get('agency')),
        category=value(row.get('category')),notice_date=value(row.get('request_date')),
        deadline=value(row.get('order_month')),status='',method=value(row.get('contract_method')),
        source_url=value(row.get('source_url')) or 'https://www.g2b.go.kr/',raw=parsed)
def kapt_row(row):
    raw=value(row.get('raw_json','{}'))
    try: parsed=json.loads(raw)
    except (ValueError,TypeError):parsed={'raw':raw}
    return dict(source='kapt',external_id=value(row.get('external_id')),
        title=value(row.get('title')),agency=value(row.get('agency')),
        category=value(row.get('category')),notice_date=value(row.get('notice_date')),
        deadline=value(row.get('deadline')),status=value(row.get('status')),
        method=value(row.get('method')),source_url=value(row.get('site_url')),raw=parsed)
def sync(source,sqlite_path,offset=0):
    sqlite_path=Path(sqlite_path)
    if not sqlite_path.exists():return offset,0,0
    table='oder_requests' if source=='g2b' else 'external_tenders'
    key='rowid' if source=='g2b' else 'id'
    imported=0;added=0
    with sqlite3.connect(f'file:{sqlite_path}?mode=ro',uri=True,timeout=30) as sq:
        sq.row_factory=sqlite3.Row
        try:
            sql=f'SELECT {key} as import_seq,* FROM {table} WHERE {key}>? ORDER BY {key} LIMIT 300'
            while True:
                rows=[dict(r) for r in sq.execute(sql,(offset,)).fetchall()]
                if not rows:break
                with session() as db:
                    for r in rows:
                        record=(g2b_row(r) if source=='g2b' else kapt_row(r))
                        if record['external_id']:
                            added+=int(store(db,record));imported+=1
                offset=rows[-1]['import_seq']
        except sqlite3.OperationalError as e:
            if 'no such table' not in str(e):raise
    return offset,imported,added
