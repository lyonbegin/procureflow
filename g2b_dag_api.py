"""Editable visual workflow registry and isolated step-debugger APIs.

Workflow editing is versioned; each debugger run freezes its graph version.
Simulation pinning/stepping is NOT a real G2B collector/Worker execution.
Production collector jobs remain under existing authenticated API endpoints.
"""
from __future__ import annotations

from json import dumps
from uuid import uuid4
from typing import Any
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from db import session
from g2b_feature_api import _case
from g2b_dag_core import (
    GraphError, validate_graph, starter_graph,
    new_debug_run, debug_action, preview_run,
)

router = APIRouter(prefix="/api/g2b/cases", tags=["G2B editable workflow & debugger"])
MAX_GRAPH_JSON = 240 * 1024


class CreateDesign(BaseModel):
    name: str = Field(default="새 워크플로", min_length=1, max_length=140)
    graph: dict[str, Any] | None = None


class UpdateDesign(BaseModel):
    expected_revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=140)
    graph: dict[str, Any]
    publish: bool = False


class DebugActionRequest(BaseModel):
    action: str
    node_id: str | None = None
    payload: Any = None


def ensure_dag_schema() -> None:
    with session() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_visual_workflows(
          id text PRIMARY KEY,
          bid_no text NOT NULL,
          name text NOT NULL,
          revision int NOT NULL DEFAULT 1,
          graph jsonb NOT NULL,
          status text NOT NULL DEFAULT 'draft',
          updated_at timestamptz NOT NULL DEFAULT now(),
          created_at timestamptz NOT NULL DEFAULT now(),
          CHECK(status IN ('draft','published','archived')))""")
        db.execute("""CREATE INDEX IF NOT EXISTS ix_pf_visual_wf_case
                   ON procureflow.g2b_visual_workflows(bid_no,updated_at DESC)""")
        db.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_visual_workflow_events(
          id bigserial PRIMARY KEY,
          bid_no text NOT NULL,
          workflow_id text NOT NULL,
          action text NOT NULL,
          revision int NOT NULL,
          details jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now())""")
        db.execute("""CREATE TABLE IF NOT EXISTS procureflow.g2b_visual_debug_runs(
          id text PRIMARY KEY,
          bid_no text NOT NULL,
          workflow_id text NOT NULL,
          graph_revision int NOT NULL,
          graph_snapshot jsonb NOT NULL,
          state jsonb NOT NULL,
          status text NOT NULL DEFAULT 'paused',
          mode text NOT NULL DEFAULT 'simulation',
          updated_at timestamptz NOT NULL DEFAULT now(),
          created_at timestamptz NOT NULL DEFAULT now())""")
        db.execute("""CREATE INDEX IF NOT EXISTS ix_pf_visual_dbg_workflow
                   ON procureflow.g2b_visual_debug_runs(bid_no,workflow_id,created_at DESC)""")


def _guard(token: str | None) -> None:
    from main import guard
    guard(token)


def _graph_json(graph: dict, publish: bool = False) -> str:
    try:
        validate_graph(graph,publish=publish)
    except GraphError as err:
        raise HTTPException(422,err.reason) from err
    raw=dumps(graph,ensure_ascii=False,allow_nan=False)
    if len(raw.encode("utf-8"))>MAX_GRAPH_JSON:
        raise HTTPException(413,"Graph exceeds 240 KiB JSON limit")
    return raw


def _get_design(db,bid_no: str,workflow_id: str,lock: bool = False):
    suffix = " FOR UPDATE" if lock else ""
    row=db.execute("""SELECT id,bid_no,name,revision,graph,status,
                       updated_at,created_at
                   FROM procureflow.g2b_visual_workflows
                   WHERE id=%s AND bid_no=%s AND status<>'archived'""" + suffix,
                   (workflow_id,bid_no)).fetchone()
    if row is None:
        raise HTTPException(404,"Workflow design not found")
    return row


def _event(db,bid_no: str,workflow_id: str,action: str,revision: int,details: dict):
    db.execute("""INSERT INTO procureflow.g2b_visual_workflow_events(
                   bid_no,workflow_id,action,revision,details)
                  VALUES(%s,%s,%s,%s,%s::jsonb)""",
                  (bid_no,workflow_id,action,revision,
                   dumps(details,ensure_ascii=False,default=str)))


@router.get("/{bid_no}/workflow/designs", summary="List independent saved visual workflows")
def list_visual_designs(bid_no: str, authorization: str | None = Header(None)):
    _guard(authorization);_case(bid_no)
    with session() as db:
        rows=db.execute("""SELECT id,name,revision,status,updated_at,created_at
                      FROM procureflow.g2b_visual_workflows
                      WHERE bid_no=%s AND status<>'archived'
                      ORDER BY updated_at DESC LIMIT 100""",(bid_no,)).fetchall()
    return {"bid_no":bid_no,"designs":[dict(row) for row in rows]}


@router.post("/{bid_no}/workflow/designs", summary="Create editable workflow from default or submitted graph")
def create_visual_design(bid_no: str,req: CreateDesign,
                         authorization: str | None = Header(None)):
    _guard(authorization);_case(bid_no)
    graph=req.graph if req.graph is not None else starter_graph()
    serialized=_graph_json(graph)
    wf_id=uuid4().hex
    with session() as db:
        db.execute("""INSERT INTO procureflow.g2b_visual_workflows(
                 id,bid_no,name,graph) VALUES(%s,%s,%s,%s::jsonb)""",
                 (wf_id,bid_no,req.name,serialized))
        _event(db,bid_no,wf_id,"created",1,{"node_count":len(graph["nodes"])})
    return {"id":wf_id,"bid_no":bid_no,"revision":1,"name":req.name,
            "status":"draft","graph":graph,"simulation_only":True}


@router.get("/{bid_no}/workflow/designs/{workflow_id}",summary="Load one versioned editable workflow graph")
def get_visual_design(bid_no: str,workflow_id: str,
                      authorization: str | None = Header(None)):
    _guard(authorization);_case(bid_no)
    with session() as db:
        row=_get_design(db,bid_no,workflow_id)
    return dict(row)


@router.put("/{bid_no}/workflow/designs/{workflow_id}",
            summary="Save edited nodes/edges with optimistic revision protection")
def update_visual_design(bid_no: str,workflow_id: str,req: UpdateDesign,
                         authorization: str | None = Header(None)):
    _guard(authorization);_case(bid_no)
    serialized=_graph_json(req.graph,publish=req.publish)
    with session() as db:
        current=_get_design(db,bid_no,workflow_id,lock=True)
        if current["revision"]!=req.expected_revision:
            raise HTTPException(409, {
                "reason":"workflow_revision_conflict",
                "server_revision":current["revision"],
                "client_revision":req.expected_revision})
        next_rev=current["revision"]+1
        next_status="published" if req.publish else "draft"
        db.execute("""UPDATE procureflow.g2b_visual_workflows
             SET name=%s,graph=%s::jsonb,revision=%s,status=%s,updated_at=now()
             WHERE id=%s AND bid_no=%s""",
             (req.name,serialized,next_rev,next_status,workflow_id,bid_no))
        _event(db,bid_no,workflow_id,"published" if req.publish else "updated",
               next_rev,{"node_count":len(req.graph["nodes"]),
                         "edge_count":len(req.graph["edges"])})
    return {"id":workflow_id,"revision":next_rev,"status":next_status,
            "graph":req.graph,"saved":True,"real_worker_started":False}


@router.delete("/{bid_no}/workflow/designs/{workflow_id}",
               summary="Archive edited workflow; existing frozen debug sessions remain")
def archive_visual_design(bid_no: str,workflow_id: str,
                          authorization: str | None = Header(None)):
    _guard(authorization);_case(bid_no)
    with session() as db:
        current=_get_design(db,bid_no,workflow_id,lock=True)
        db.execute("""UPDATE procureflow.g2b_visual_workflows
                     SET status='archived',updated_at=now() WHERE id=%s AND bid_no=%s""",
                   (workflow_id,bid_no))
        _event(db,bid_no,workflow_id,"archived",current["revision"],{})
    return {"id":workflow_id,"archived":True,"historical_debug_runs_preserved":True}


@router.post("/{bid_no}/workflow/designs/{workflow_id}/debug-runs",
             summary="Start isolated dry-run debugger freezing the graph revision")
def start_visual_debug_run(bid_no: str,workflow_id: str,
                           authorization: str | None = Header(None)):
    _guard(authorization);_case(bid_no)
    with session() as db:
        design=_get_design(db,bid_no,workflow_id)
        graph=design["graph"]
        try:
            state=new_debug_run(graph)
        except GraphError as err:
            raise HTTPException(422,err.reason) from err
        run_id=uuid4().hex
        db.execute("""INSERT INTO procureflow.g2b_visual_debug_runs(
             id,bid_no,workflow_id,graph_revision,graph_snapshot,state)
             VALUES(%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
             (run_id,bid_no,workflow_id,design["revision"],
              dumps(graph,ensure_ascii=False),dumps(state,ensure_ascii=False)))
        _event(db,bid_no,workflow_id,"debug_started",design["revision"],
               {"debug_run_id":run_id})
    return {"id":run_id,"workflow_id":workflow_id,"graph_revision":design["revision"],
            "result":preview_run(graph,state),"production_job_created":False}


def _get_run(db,bid_no: str,run_id: str,lock: bool = False):
    suffix=" FOR UPDATE" if lock else ""
    row=db.execute("""SELECT id,bid_no,workflow_id,graph_revision,graph_snapshot,
                   state,status,updated_at,created_at
                   FROM procureflow.g2b_visual_debug_runs
                   WHERE id=%s AND bid_no=%s""" + suffix,
                   (run_id,bid_no)).fetchone()
    if row is None:raise HTTPException(404,"Debugger run not found")
    return row


@router.get("/{bid_no}/workflow/debug-runs/{run_id}",
            summary="Observe all simulated node states, connections and pinned outputs")
def view_visual_debug_run(bid_no: str,run_id: str,
                          authorization: str | None = Header(None)):
    _guard(authorization);_case(bid_no)
    with session() as db:
        run=_get_run(db,bid_no,run_id)
    return {"id":run_id,"workflow_id":run["workflow_id"],
            "graph_revision":run["graph_revision"],
            "result":preview_run(run["graph_snapshot"],run["state"])}


@router.post("/{bid_no}/workflow/debug-runs/{run_id}/actions",
             summary="Safe pause/resume/stop/step/skip/retry/pin simulated node")
def control_visual_debug_run(bid_no: str,run_id: str,request: DebugActionRequest,
                             authorization: str | None = Header(None)):
    _guard(authorization);_case(bid_no)
    if request.action not in ("pause","resume","stop","step","continue","skip","retry","pin","fail"):
        raise HTTPException(422,"Unsupported debugger control")
    with session() as db:
        current=_get_run(db,bid_no,run_id,lock=True)
        try:
            updated=debug_action(current["graph_snapshot"],current["state"],
                                 request.action,node_id=request.node_id,
                                 payload=request.payload)
        except GraphError as err:
            raise HTTPException(409,err.reason) from err
        raw=dumps(updated,ensure_ascii=False,default=str)
        if len(raw.encode("utf-8"))>MAX_GRAPH_JSON:
            raise HTTPException(413,"Debug-run event/output storage limit exceeded")
        db.execute("""UPDATE procureflow.g2b_visual_debug_runs
             SET state=%s::jsonb,status=%s,updated_at=now()
             WHERE id=%s AND bid_no=%s""",
             (raw,updated["status"],run_id,bid_no))
        _event(db,bid_no,current["workflow_id"],"debug_"+request.action,
               current["graph_revision"],{"run_id":run_id,"node_id":request.node_id})
    return {"id":run_id,"graph_revision":current["graph_revision"],
            "result":preview_run(current["graph_snapshot"],updated),
            "no_real_collector_executed":True}
