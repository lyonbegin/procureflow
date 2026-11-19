"""Durable, observation-only telemetry for the public HITEL research job API.

Heartbeat means transport contact, never model progress.  The additional table
does not change pre-existing room, message, or result records.
"""
from __future__ import annotations

import base64
import hashlib
import json

import api_v1

PUBLIC_USER = "usr_browser_hitel_public_link"
MAX_RESULT_CHUNK_BYTES = 65536

def initialize():
    with api_v1.connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS hitel_public_job_observations (
          job_id TEXT PRIMARY KEY,
          event_stage TEXT,
          job_last_progress_at INTEGER,
          worker_heartbeat_at INTEGER,
          chatgpt_send_confirmed INTEGER,
          assistant_reply_observed INTEGER,
          error_code TEXT,
          error_stage TEXT
        )""")

def observe(job_id, stage=None, *, send_confirmed=False, reply_observed=False,
            error_code=None, error_stage=None):
    """Record only an actual authenticated worker event, not a polling interval."""
    now=api_v1.clock()
    with api_v1.connection() as db:
        allowed=db.execute("SELECT 1 FROM jobs WHERE id=? AND user_id=?",
                           (job_id,PUBLIC_USER)).fetchone()
        if not allowed:
            return False
        db.execute("""INSERT OR IGNORE INTO hitel_public_job_observations(job_id)
                      VALUES(?)""",(job_id,))
        if stage is not None:
            db.execute("""UPDATE hitel_public_job_observations
                          SET event_stage=?,job_last_progress_at=?
                          WHERE job_id=?""",(stage,now,job_id))
        if send_confirmed:
            db.execute("""UPDATE hitel_public_job_observations
                          SET chatgpt_send_confirmed=1 WHERE job_id=?""",(job_id,))
        if reply_observed:
            db.execute("""UPDATE hitel_public_job_observations
                          SET assistant_reply_observed=1 WHERE job_id=?""",(job_id,))
        if error_code is not None:
            db.execute("""UPDATE hitel_public_job_observations
                          SET error_code=?,error_stage=?
                          WHERE job_id=?""",(error_code,error_stage,job_id))
    return True

def heartbeat(job_id):
    """Worker ping is not a research-progress event."""
    with api_v1.connection() as db:
        if not db.execute("SELECT 1 FROM jobs WHERE id=? AND user_id=?",
                          (job_id,PUBLIC_USER)).fetchone():
            return False
        db.execute("""INSERT OR IGNORE INTO hitel_public_job_observations(job_id)
                      VALUES(?)""",(job_id,))
        db.execute("""UPDATE hitel_public_job_observations
                      SET worker_heartbeat_at=? WHERE job_id=?""",
                   (api_v1.clock(),job_id))
    return True

def job_row(job_id):
    with api_v1.connection() as db:
        row=db.execute("""SELECT j.id,j.room_id,r.title AS room_name,j.status,
                          j.stage,j.result_text,j.error,j.created_at,j.updated_at,
                          p.request_id,
                          o.event_stage,o.job_last_progress_at,
                          o.worker_heartbeat_at,o.chatgpt_send_confirmed,
                          o.assistant_reply_observed,o.error_code,o.error_stage
                     FROM jobs j
                     JOIN rooms r ON r.id=j.room_id AND r.user_id=j.user_id
                     JOIN hitel_public_link_requests p ON p.job_id=j.id
                     LEFT JOIN hitel_public_job_observations o ON o.job_id=j.id
                     WHERE j.id=? AND j.user_id=? AND j.account_id IS NULL""",
                     (job_id,PUBLIC_USER)).fetchone()
    return dict(row) if row else None

def result_metadata(text):
    raw=text.encode("utf-8")
    try:
        parsed=json.loads(text)
        valid=isinstance(parsed,dict)
    except (json.JSONDecodeError, ValueError):
        valid=False
    return {
        "result_length_bytes":len(raw),
        "result_sha256":hashlib.sha256(raw).hexdigest(),
        "result_json_valid":valid,
        "result_json_complete":valid,
        "result_chunk_count":(len(raw)+MAX_RESULT_CHUNK_BYTES-1)//MAX_RESULT_CHUNK_BYTES,
    }

def result_slice(text, offset=0, limit=MAX_RESULT_CHUNK_BYTES):
    if not 0<=offset or not 1<=limit<=MAX_RESULT_CHUNK_BYTES:
        raise ValueError("INVALID_RESULT_BYTE_RANGE")
    raw=text.encode("utf-8")
    if offset>len(raw):
        raise ValueError("RESULT_OFFSET_OUT_OF_BOUNDS")
    chunk=raw[offset:offset+limit]
    return {
        "offset":offset,"bytes_returned":len(chunk),
        "next_offset":offset+len(chunk),
        "complete":offset+len(chunk)==len(raw),
        "content_base64":base64.b64encode(chunk).decode("ascii"),
        **result_metadata(text),
    }
