"""Selected-G2B-tender node test lab.

This is a *test-only* input/response harness. It NEVER publishes official
evidence, writes a tender/bid result, calls arbitrary user URLs, or submits.
Modes:
  official  -> read the actual stored observation without running collectors
  manual    -> validate and inspect manually entered JSON values
  file      -> parse user-uploaded fixture files using existing document parser
  mock      -> return caller-provided deterministic mock response
Actual collector execution is the existing separately authenticated /run API.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from typing import Any, Literal
from uuid import uuid4
import json
import re
import zipfile

from fastapi import APIRouter, File, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from db import session
from g2b_feature_api import _case, CATALOG, normalize_params, notice_context

router = APIRouter(prefix="/api/g2b/cases", tags=["G2B node lab - isolated test fixtures"])

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_FILES_PER_NODE = 12
MAX_REQUEST_BYTES = 128 * 1024
MAX_ARCHIVE_ITEMS = 600
MAX_ARCHIVE_UNCOMPRESSED = 32 * 1024 * 1024
MAX_ARCHIVE_RATIO = 150
EXTENSIONS = {"pdf", "hwp", "hwpx", "docx", "xlsx", "csv", "txt", "json", "xml"}
ALLOWED_ASSERT = {"eq", "ne", "exists", "contains", "gte", "lte"}


class Assertion(BaseModel):
    path: str = Field(min_length=1, max_length=160, pattern=r"^\$?(?:[A-Za-z_][A-Za-z0-9_]*|\.[A-Za-z_][A-Za-z0-9_]*|\[[0-9]+\])(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[0-9]+\])*$")
    operator: Literal["eq", "ne", "exists", "contains", "gte", "lte"] = "eq"
    expected: Any = None


class NodeTestRequest(BaseModel):
    mode: Literal["official", "manual", "file", "mock"] = "official"
    parameters: dict[str, Any] = Field(default_factory=dict)
    variables: dict[str, Any] = Field(default_factory=dict)
    file_ids: list[str] = Field(default_factory=list, max_length=6)
    mock_output: Any = None
    assertions: list[Assertion] = Field(default_factory=list, max_length=30)


class PinRequest(BaseModel):
    label: str = Field(default="pinned-test-output", min_length=1, max_length=120)
    output: Any


def ensure_node_lab() -> None:
    with session() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_node_test_files(
          id text PRIMARY KEY,
          bid_no text NOT NULL,
          feature_no int NOT NULL CHECK(feature_no BETWEEN 1 AND 104),
          filename text NOT NULL,
          mime text NOT NULL DEFAULT '',
          sha256 text NOT NULL,
          size_bytes bigint NOT NULL,
          file_bytes bytea NOT NULL,
          parse_state text NOT NULL,
          text_preview text NOT NULL DEFAULT '',
          is_test_fixture boolean NOT NULL DEFAULT true,
          created_at timestamptz NOT NULL DEFAULT now())""")
        c.execute("""CREATE INDEX IF NOT EXISTS ix_pf_node_test_files
                     ON procureflow.g2b_node_test_files(bid_no,feature_no,created_at DESC)""")
        c.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_node_test_runs(
          id bigserial PRIMARY KEY,
          bid_no text NOT NULL,
          feature_no int NOT NULL CHECK(feature_no BETWEEN 1 AND 104),
          mode text NOT NULL,
          request jsonb NOT NULL,
          result jsonb NOT NULL,
          input_sha256 text NOT NULL,
          status text NOT NULL,
          is_test_only boolean NOT NULL DEFAULT true,
          duration_ms int NOT NULL DEFAULT 0,
          created_at timestamptz NOT NULL DEFAULT now())""")
        c.execute("""CREATE INDEX IF NOT EXISTS ix_pf_node_test_runs
                     ON procureflow.g2b_node_test_runs(bid_no,feature_no,id DESC)""")
        c.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_node_test_pins(
          bid_no text NOT NULL,feature_no int NOT NULL,
          label text NOT NULL,output jsonb NOT NULL,
          source text NOT NULL DEFAULT 'test_only',
          updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY(bid_no,feature_no))""")


def _auth(token: str | None) -> None:
    from main import guard
    guard(token)


def _validate(bid_no: str, number: int) -> None:
    _case(bid_no)
    if number not in CATALOG:
        raise HTTPException(404, "Unknown G2B function number")


def _safe_json_size(value: Any, limit: int = MAX_REQUEST_BYTES) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(raw.encode("utf-8")) > limit:
        raise HTTPException(413, f"JSON test payload exceeds {limit} bytes")
    return raw


def _safe_filename(name: str) -> str:
    # Browsers may send a full path; strip it and reject untrusted control chars.
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or len(name) > 150 or any(ord(ch) < 32 for ch in name):
        raise HTTPException(422, "Invalid test-file name")
    if name in (".", ".."):
        raise HTTPException(422, "Invalid test-file name")
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if extension not in EXTENSIONS:
        raise HTTPException(415, "Unsupported test file format")
    return name


def _validate_document(name: str, raw: bytes) -> None:
    extension = name.rsplit(".", 1)[-1].lower()
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise HTTPException(413, "Empty or oversized test file")
    if extension == "pdf" and not raw.startswith(b"%PDF-"):
        raise HTTPException(415, "PDF file signature mismatch")
    if extension == "hwp" and not raw.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        raise HTTPException(415, "HWP OLE signature mismatch")
    if extension in {"docx", "xlsx", "hwpx"}:
        if not zipfile.is_zipfile(BytesIO(raw)):
            raise HTTPException(415, "ZIP/Office signature mismatch")
        try:
            with zipfile.ZipFile(BytesIO(raw)) as archive:
                infos = archive.infolist()
                if len(infos) > MAX_ARCHIVE_ITEMS:
                    raise HTTPException(413, "Too many archive entries")
                total = sum(part.file_size for part in infos)
                if total > MAX_ARCHIVE_UNCOMPRESSED:
                    raise HTTPException(413, "Uncompressed archive too large")
                if any(part.file_size > MAX_ARCHIVE_RATIO * max(1, part.compress_size)
                       for part in infos if part.file_size > 1024):
                    raise HTTPException(413, "Compressed archive expansion ratio too high")
                if any(part.flag_bits & 0x1 for part in infos):
                    raise HTTPException(415, "Encrypted ZIP files are not supported")
                required = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml",
                            "hwpx": "Contents/content.hpf"}[extension]
                if required not in archive.namelist() and not (
                    extension == "hwpx" and any(x.startswith("Contents/section") for x in archive.namelist())):
                    raise HTTPException(415, "File does not match declared Office format")
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise HTTPException(415, "Invalid compressed document") from exc
    if extension in {"csv", "txt", "json", "xml"} and b"\x00" in raw[:1024]:
        raise HTTPException(415, "Binary data masquerading as text")


def _get_path(result: Any, path: str) -> tuple[bool, Any]:
    pointer = path.removeprefix("$").lstrip(".")
    if not pointer:
        return True, result
    chunks = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\[[0-9]+\]", pointer)
    value = result
    for token in chunks:
        if token.startswith("["):
            idx = int(token[1:-1])
            if not isinstance(value, list) or idx >= len(value):
                return False, None
            value = value[idx]
        else:
            if not isinstance(value, dict) or token not in value:
                return False, None
            value = value[token]
    return True, value


def _assert_one(result: Any, assertion: Assertion) -> dict:
    found, observed = _get_path(result, assertion.path)
    expected = assertion.expected
    try:
        op = assertion.operator
        if op == "exists":
            passed = found == (bool(expected) if expected is not None else True)
        elif not found:
            passed = False
        elif op == "eq":
            passed = observed == expected
        elif op == "ne":
            passed = observed != expected
        elif op == "contains":
            passed = (expected in observed) if isinstance(observed, (str, list, dict)) else False
        elif op == "gte":
            passed = isinstance(observed, (int, float)) and not isinstance(observed, bool) and observed >= expected
        elif op == "lte":
            passed = isinstance(observed, (int, float)) and not isinstance(observed, bool) and observed <= expected
        else:
            passed = False
    except (TypeError, ValueError):
        passed = False
    return {"path": assertion.path, "operator": assertion.operator, "expected": expected,
            "actual": observed if found else None, "found": found, "passed": bool(passed)}


def _fetch_fixtures(bid_no: str, number: int, ids: list[str]) -> list[dict]:
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Duplicate test file IDs")
    if not ids:
        raise HTTPException(422, "File mode requires one or more uploaded test files")
    with session() as c:
        files = c.execute("""SELECT id,filename,mime,sha256,size_bytes,
                          parse_state,text_preview
                       FROM procureflow.g2b_node_test_files
                       WHERE bid_no=%s AND feature_no=%s AND id=ANY(%s)
                       ORDER BY id""", (bid_no, number, ids)).fetchall()
    if len(files) != len(ids):
        raise HTTPException(404, "One or more test files do not belong to the selected feature")
    return [dict(f) for f in files]


def _run_test(bid_no: str, number: int, request: NodeTestRequest) -> dict:
    _validate(bid_no, number)
    _safe_json_size(request.model_dump())
    # parameters may be passed only where collector interface documents them.
    try:
        params = normalize_params(number, request.parameters)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if request.mode == "official":
        if request.variables or request.file_ids or request.mock_output is not None:
            raise HTTPException(422, "Official observation cannot accept manual source overrides")
        from g2b_feature_data import feature_observation
        context = notice_context(bid_no)
        observed = feature_observation(number, context)
        output = {"observation": observed}
        processing = "read_only_actual_feature_observation"
    elif request.mode == "manual":
        if request.file_ids or request.mock_output is not None:
            raise HTTPException(422, "Manual JSON mode accepts variables only")
        output = {"input": request.variables, "parameters": params,
                  "origin": "unverified_user_test_fixture"}
        processing = "manual_fixture_validation_echo_not_business_function"
    elif request.mode == "file":
        if request.mock_output is not None:
            raise HTTPException(422, "File test mode does not accept mock response")
        files = _fetch_fixtures(bid_no, number, request.file_ids)
        output = {"files": [
            {"id": file["id"], "name": file["filename"], "size": file["size_bytes"],
             "sha256": file["sha256"], "parse_state": file["parse_state"],
             "text_preview": file["text_preview"]}
            for file in files],
            "variables": request.variables, "origin": "unverified_file_fixture"}
        processing = "actual_file_parsing_at_upload_then_test_fixture_inspection"
    else:
        if request.file_ids:
            raise HTTPException(422, "Mock response mode does not accept file IDs")
        output = request.mock_output
        processing = "user_supplied_mock_response_no_external_request"
    assertions = [_assert_one(output, assertion) for assertion in request.assertions]
    passed = all(item["passed"] for item in assertions)
    return {
        "bid_no": bid_no, "feature_no": number, "mode": request.mode,
        "test_only": True, "is_official_evidence": False,
        "production_acceptance_updated": False, "collector_was_executed": False,
        "processing": processing,
        "status": "pass" if passed else "assertion_failed",
        "http_status": 200, "output": output,
        "assertions": assertions, "assertions_passed": passed,
    }


@router.get("/{bid_no}/features/{feature_no}/test/contract",
            summary="Read permitted standalone node test inputs and examples")
def node_test_contract(bid_no: str, feature_no: int,
                       authorization: str | None = Header(None)):
    _auth(authorization)
    _validate(bid_no, feature_no)
    from g2b_feature_api import contract_params
    return {
        "bid_no": bid_no, "feature_no": feature_no,
        "modes": ["official", "manual", "file", "mock"],
        "additional_parameters": contract_params(feature_no),
        "available_file_formats": sorted(EXTENSIONS),
        "max_file_bytes": MAX_FILE_BYTES, "max_files_per_node": MAX_FILES_PER_NODE,
        "max_files_per_test": 6, "test_isolation": True,
        "official_mode_read_only": True, "no_arbitrary_http_proxy": True,
        "no_bid_submission": True,
        "examples": {
            "manual": {"mode": "manual", "variables": {"example": "typed test value"}},
            "mock": {"mode": "mock", "mock_output": {"status": "success"}},
        },
    }


@router.post("/{bid_no}/features/{feature_no}/test",
             summary="Run isolated manual JSON, file, mock, or read-only official test")
def run_node_test(bid_no: str, feature_no: int, request: NodeTestRequest,
                  authorization: str | None = Header(None)):
    _auth(authorization)
    _validate(bid_no, feature_no)
    begin = datetime.now(timezone.utc)
    result = _run_test(bid_no, feature_no, request)
    duration = max(0, int((datetime.now(timezone.utc) - begin).total_seconds() * 1000))
    safe_request = request.model_dump()
    # Never store uploaded binary data or authentication credentials in run rows.
    request_json = _safe_json_size(safe_request)
    output_json = _safe_json_size(result, limit=256 * 1024)
    with session() as c:
        row = c.execute("""INSERT INTO procureflow.g2b_node_test_runs(
            bid_no,feature_no,mode,request,result,input_sha256,status,duration_ms)
            VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s)
            RETURNING id""", (
                bid_no, feature_no, request.mode, request_json, output_json,
                sha256(request_json.encode("utf-8")).hexdigest(), result["status"], duration,
            )).fetchone()
    return {**result, "run_id": row["id"], "duration_ms": duration}


@router.get("/{bid_no}/features/{feature_no}/test/runs",
            summary="Inspect isolated node test history and inputs for replay")
def get_node_test_runs(bid_no: str, feature_no: int,
                       authorization: str | None = Header(None),
                       limit: int = Query(15, ge=1, le=50)):
    _auth(authorization)
    _validate(bid_no, feature_no)
    with session() as c:
        rows = c.execute("""SELECT id,mode,request,result,status,
                   input_sha256,duration_ms,created_at
                  FROM procureflow.g2b_node_test_runs
                  WHERE bid_no=%s AND feature_no=%s
                  ORDER BY id DESC LIMIT %s""",
                  (bid_no, feature_no, limit)).fetchall()
    return {"bid_no": bid_no, "feature_no": feature_no,
            "runs": [dict(row) for row in rows],
            "test_only": True}


@router.post("/{bid_no}/features/{feature_no}/test/files",
             summary="Upload one isolated document test fixture (max 8 MiB)")
async def upload_node_test_file(bid_no: str, feature_no: int,
                                file: UploadFile = File(...),
                                authorization: str | None = Header(None)):
    _auth(authorization)
    _validate(bid_no, feature_no)
    filename = _safe_filename(file.filename or "")
    raw = await file.read(MAX_FILE_BYTES + 1)
    await file.close()
    _validate_document(filename, raw)
    from g2b_documents import extract_file
    try:
        parse_state, preview = extract_file(filename, raw)
    except Exception as exc:
        parse_state, preview = "parse_error_" + type(exc).__name__, ""
    ident = uuid4().hex
    digest = sha256(raw).hexdigest()
    with session() as c:
        count = c.execute("""SELECT count(*)::int AS count FROM procureflow.g2b_node_test_files
                  WHERE bid_no=%s AND feature_no=%s""", (bid_no, feature_no)).fetchone()["count"]
        if count >= MAX_FILES_PER_NODE:
            raise HTTPException(409, "Feature test-file limit reached: remove old fixtures first")
        c.execute("""INSERT INTO procureflow.g2b_node_test_files(
                   id,bid_no,feature_no,filename,mime,sha256,size_bytes,
                   file_bytes,parse_state,text_preview)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                  (ident,bid_no,feature_no,filename,file.content_type or "",
                   digest,len(raw),raw,parse_state,preview[:12000]))
    return {"id": ident, "bid_no":bid_no, "feature_no":feature_no,
            "filename":filename, "size_bytes":len(raw),"sha256":digest,
            "parse_state":parse_state,"text_preview":preview[:12000],
            "test_only":True,"official_source_verified":False,
            "production_evidence_updated":False}


@router.get("/{bid_no}/features/{feature_no}/test/files",
            summary="List uploaded test fixtures without exposing source bytes")
def list_node_test_files(bid_no: str, feature_no: int,
                         authorization: str | None = Header(None)):
    _auth(authorization)
    _validate(bid_no, feature_no)
    with session() as c:
        rows = c.execute("""SELECT id,filename,mime,sha256,size_bytes,parse_state,
                            text_preview,created_at
                       FROM procureflow.g2b_node_test_files
                       WHERE bid_no=%s AND feature_no=%s
                       ORDER BY created_at DESC""", (bid_no, feature_no)).fetchall()
    return {"files":[dict(row) for row in rows],
            "test_only": True, "official_source_verified": False}


@router.delete("/{bid_no}/features/{feature_no}/test/files/{file_id}",
               summary="Remove a test fixture without changing original attachments")
def delete_node_test_file(bid_no: str, feature_no: int, file_id: str,
                          authorization: str | None = Header(None)):
    _auth(authorization)
    _validate(bid_no, feature_no)
    with session() as c:
        row = c.execute("""DELETE FROM procureflow.g2b_node_test_files
               WHERE bid_no=%s AND feature_no=%s AND id=%s RETURNING id""",
               (bid_no, feature_no, file_id)).fetchone()
    if not row:
        raise HTTPException(404, "Test fixture not found")
    return {"removed_test_file_id":file_id, "official_source_unchanged":True}


@router.get("/{bid_no}/features/{feature_no}/test/pin",
            summary="Read pinned test output for deterministic replay")
def read_node_test_pin(bid_no: str, feature_no: int,
                       authorization: str | None = Header(None)):
    _auth(authorization)
    _validate(bid_no, feature_no)
    with session() as c:
        row = c.execute("""SELECT label,output,source,updated_at
                 FROM procureflow.g2b_node_test_pins WHERE bid_no=%s AND feature_no=%s""",
                 (bid_no,feature_no)).fetchone()
    return {"pin":dict(row) if row else None, "test_only":True}


@router.put("/{bid_no}/features/{feature_no}/test/pin",
            summary="Save a fixture response; never replace official evidence")
def save_node_test_pin(bid_no: str, feature_no: int, request: PinRequest,
                       authorization: str | None = Header(None)):
    _auth(authorization)
    _validate(bid_no, feature_no)
    output_json = _safe_json_size(request.output, limit=128 * 1024)
    with session() as c:
        c.execute("""INSERT INTO procureflow.g2b_node_test_pins(
                    bid_no,feature_no,label,output)
                    VALUES(%s,%s,%s,%s::jsonb)
                    ON CONFLICT(bid_no,feature_no) DO UPDATE
                    SET label=excluded.label,output=excluded.output,updated_at=now()""",
                   (bid_no,feature_no,request.label,output_json))
    return {"feature_no":feature_no,"pinned":True,"test_only":True,
            "production_acceptance_updated":False}


@router.delete("/{bid_no}/features/{feature_no}/test/pin",
               summary="Clear pinned fixture response")
def delete_node_test_pin(bid_no: str, feature_no: int,
                         authorization: str | None = Header(None)):
    _auth(authorization)
    _validate(bid_no, feature_no)
    with session() as c:
        c.execute("""DELETE FROM procureflow.g2b_node_test_pins
                 WHERE bid_no=%s AND feature_no=%s""",(bid_no,feature_no))
    return {"feature_no":feature_no,"pinned":False,"test_only":True}
