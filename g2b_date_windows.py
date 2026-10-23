"""Validating explicit calendar windows for G2B historical web collection.

All times are interpreted as Asia/Seoul, and date ranges are inclusive.
A backfill job has a fixed YYYY-MM-DD range; it never silently shifts with
the worker's current clock when it is queued and executed on different days.
"""
from datetime import date,datetime,timedelta,timezone
KST=timezone(timedelta(hours=9))


def window(days, start_date=None, end_date=None, max_span_days=31):
    if bool(start_date)!=bool(end_date):
        raise ValueError("Both start_date and end_date are required together")
    if start_date:
        start=date.fromisoformat(start_date)
        end=date.fromisoformat(end_date)
    else:
        end=datetime.now(KST).date()
        start=end-timedelta(days=max(1,min(int(days),max_span_days)))
    if end<start or (end-start).days>max_span_days:
        raise ValueError("G2B date-window exceeds supported range")
    if end>datetime.now(KST).date():
        raise ValueError("G2B date-window ends in the future")
    if start.year<2010:
        raise ValueError("G2B historical date outside supported window")
    return start,end
