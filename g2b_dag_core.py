"""Pure, deterministic selected-tender workflow graph and step debugger.

Editing a graph does not execute it. The debugger is an isolated simulation:
its node outputs come from explicit test fixtures/pins, NEVER from a fabricated
G2B collector result. No network calls, bid submission, signing or writes.
"""
from __future__ import annotations
from copy import deepcopy
from collections import deque
from typing import Any
import re

MAX_NODES = 250
MAX_EDGES = 500
TERMINAL = {"succeeded", "failed", "skipped", "blocked", "cancelled"}
SATISFIED = {"succeeded"}
CONDITIONS = {"success", "failure", "always", "skipped"}
JOINS = {"all", "any", "quorum", "all_settled"}
KINDS = {"start", "feature", "join", "condition", "end", "note"}
PATH_PATTERN = re.compile(r"^\$?(?:[A-Za-z_][\w]*|\.[A-Za-z_][\w]*)(?:\.[A-Za-z_][\w]*|\[[0-9]+\])*$")


class GraphError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _id(x: Any) -> bool:
    return isinstance(x, str) and 1 <= len(x) <= 90 and re.fullmatch(r"[A-Za-z0-9:_-]+", x) is not None


def validate_graph(graph: dict, publish: bool = False) -> dict:
    if not isinstance(graph, dict):
        raise GraphError("Graph must be an object")
    nodes, edges = graph.get("nodes"), graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise GraphError("nodes and edges must be arrays")
    if not (1 <= len(nodes) <= MAX_NODES) or len(edges) > MAX_EDGES:
        raise GraphError("graph_size_limit_exceeded")
    node_ids, edge_ids = set(), set()
    starts = []
    for node in nodes:
        if not isinstance(node, dict):
            raise GraphError("invalid_node")
        node_id = node.get("id")
        if not _id(node_id) or node_id in node_ids:
            raise GraphError("duplicate_or_invalid_node_id")
        node_ids.add(node_id)
        kind = node.get("type")
        if kind not in KINDS:
            raise GraphError("unsupported_node_type:" + str(kind))
        if kind == "start":
            starts.append(node_id)
        if kind == "feature":
            number = node.get("feature_no")
            if type(number) is not int or number not in range(1, 105):
                raise GraphError("feature_nodes_require_1_to_104_feature_number")
        position = node.get("position")
        if not isinstance(position, dict) or any(
            type(position.get(k)) not in (int, float) or abs(position[k]) > 1_000_000
            for k in ("x", "y")
        ):
            raise GraphError("node_position_missing_or_invalid")
        policy = node.get("join", {"mode": "all"})
        if not isinstance(policy, dict) or policy.get("mode", "all") not in JOINS:
            raise GraphError("unsupported_join_policy")
        if policy.get("mode") == "quorum" and (
            type(policy.get("minimum")) is not int or policy["minimum"] < 1 or
            policy["minimum"] > MAX_NODES
        ):
            raise GraphError("quorum_requires_positive_minimum")
    if len(starts) != 1:
        raise GraphError("exactly_one_tender_start_required")
    neighbours, incoming, indegree = {key: [] for key in node_ids}, {key: [] for key in node_ids}, {key: 0 for key in node_ids}
    for edge in edges:
        if not isinstance(edge, dict):
            raise GraphError("invalid_edge")
        edge_id, source, target = edge.get("id"), edge.get("source"), edge.get("target")
        if not _id(edge_id) or edge_id in edge_ids:
            raise GraphError("duplicate_or_invalid_edge_id")
        edge_ids.add(edge_id)
        if source not in node_ids or target not in node_ids or source == target:
            raise GraphError("edge_connects_unknown_or_same_node")
        if target in starts:
            raise GraphError("no_edge_can_target_tender_start")
        if edge.get("when", "success") not in CONDITIONS:
            raise GraphError("unsupported_edge_condition")
        mappings = edge.get("mapping", {})
        if not isinstance(mappings, dict) or len(mappings) > 50:
            raise GraphError("invalid_output_input_mapping")
        for source_path, dest_path in mappings.items():
            if not isinstance(source_path, str) or not isinstance(dest_path, str) or not (
                PATH_PATTERN.fullmatch(source_path) and PATH_PATTERN.fullmatch(dest_path)
            ):
                raise GraphError("unsafe_json_mapping_path")
        neighbours[source].append(target)
        incoming[target].append(edge)
        indegree[target] += 1
    queue = deque(sorted(node for node in node_ids if indegree[node] == 0))
    visited = []
    while queue:
        item = queue.popleft()
        visited.append(item)
        for target in neighbours[item]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if len(visited) != len(node_ids):
        raise GraphError("cyclic_workflows_are_forbidden")
    if publish:
        reachable = {starts[0]}
        queue = deque(starts)
        while queue:
            n = queue.popleft()
            for target in neighbours[n]:
                if target not in reachable:
                    reachable.add(target)
                    queue.append(target)
        if reachable != node_ids:
            raise GraphError("published_graph_cannot_have_disconnected_nodes")
        for node in nodes:
            if node["type"] != "start" and not incoming[node["id"]]:
                raise GraphError("published_nonstart_node_missing_incoming_edge")
            if node.get("join", {}).get("mode") == "quorum" and (
                node["join"]["minimum"] > len(incoming[node["id"]])
            ):
                raise GraphError("quorum_minimum_exceeds_input_count")
    return {"nodes": nodes, "edges": edges, "topological_order": visited,
            "start_id": starts[0], "incoming": incoming, "neighbours": neighbours}


def starter_graph() -> dict:
    """Small editable default illustrating parallel branches and ALL join.

    The graph is a *design example*, not a claim about production evidence.
    Node 104 still requires independent human approval before a bid is sent.
    """
    nodes = [
        ("tender", "start", None, 0, 220, "선택한 발주정보"),
        ("notice", "feature", 1, 290, 220, "공식 원본 확인"),
        ("history", "feature", 50, 610, 40, "10년 개찰·낙찰"),
        ("documents", "feature", 29, 610, 220, "첨부문서 수집"),
        ("eligibility", "feature", 66, 610, 400, "참가자격 검토"),
        ("join", "join", None, 950, 220, "입찰 준비 필수 정보 ALL"),
        ("price", "feature", 89, 1230, 220, "가격 시나리오 검토"),
        ("finish", "end", None, 1540, 220, "입찰참가 직전 승인"),
    ]
    result_nodes = [
        {"id": name, "type": kind, "feature_no": feature_no,
         "label": label, "position": {"x": x, "y": y},
         "join": {"mode": "all"}, "breakpoint_before": False,
         "breakpoint_after": False}
        for name,kind,feature_no,x,y,label in nodes
    ]
    pairs = [
        ("tender","notice"),("notice","history"),("notice","documents"),
        ("notice","eligibility"),("history","join"),("documents","join"),
        ("eligibility","join"),("join","price"),("price","finish"),
    ]
    result_edges = [
        {"id":f"edge-{source}-{target}","source":source,"target":target,
         "when":"success","mapping":{}}
        for source,target in pairs
    ]
    return {"nodes":result_nodes,"edges":result_edges,
            "description":"Editable starter graph; not a production collector or approved bid"}


def _matches(state: str, condition: str) -> bool:
    if condition == "success": return state == "succeeded"
    if condition == "failure": return state in ("failed", "blocked", "cancelled")
    if condition == "skipped": return state == "skipped"
    return state in TERMINAL


def _node_gate(node: dict, incoming: list[dict], states: dict) -> str:
    if not incoming:
        return "ready" if node["type"] == "start" else "blocked"
    results = [(edge, states.get(edge["source"], "pending")) for edge in incoming]
    matched = sum(_matches(state, edge.get("when", "success")) for edge,state in results)
    done = sum(state in TERMINAL for _,state in results)
    count = len(results)
    policy = node.get("join", {}).get("mode", "all")
    if policy == "all":
        if done == count:
            return "ready" if matched == count else "blocked"
    elif policy == "any":
        if matched >= 1: return "ready"
        if done == count: return "blocked"
    elif policy == "quorum":
        minimum = node.get("join", {}).get("minimum", 1)
        if matched >= minimum: return "ready"
        if (count - done + matched) < minimum: return "blocked"
    elif policy == "all_settled":
        if done == count: return "ready"
    return "waiting"


def runnable_nodes(graph: dict, run: dict) -> dict:
    structure = validate_graph(graph)
    states = run.get("states", {})
    by_id = {node["id"]: node for node in graph["nodes"]}
    ready,blocked,waiting = [],[],[]
    for node_id in structure["topological_order"]:
        state = states.get(node_id, "pending")
        if state not in ("pending", "ready"):
            continue
        gate = _node_gate(by_id[node_id], structure["incoming"][node_id], states)
        if gate == "ready": ready.append(node_id)
        elif gate == "blocked": blocked.append(node_id)
        else: waiting.append(node_id)
    return {"ready":ready,"blocked":blocked,"waiting":waiting,
            "simulated_parallel_ready":len(ready)>1}


def _json_path_read(value: Any, path: str) -> tuple[bool, Any]:
    """Constrained data binding; no eval, code, SQL or user-defined functions."""
    if not PATH_PATTERN.fullmatch(path):
        raise GraphError("unsafe_source_mapping_path")
    chunks = re.findall(r"[A-Za-z_]\w*|\[[0-9]+\]", path.lstrip("$."))
    for part in chunks:
        if part.startswith("["):
            index = int(part[1:-1])
            if not isinstance(value, list) or not 0 <= index < len(value):
                return False, None
            value = value[index]
        else:
            if not isinstance(value, dict) or part not in value:
                return False, None
            value = value[part]
    return True, deepcopy(value)


def _json_path_write(target: dict, path: str, value: Any) -> None:
    if not PATH_PATTERN.fullmatch(path):
        raise GraphError("unsafe_target_mapping_path")
    parts = path.lstrip("$.").split(".")
    if len(parts) > 12 or any("[" in part for part in parts):
        # All target paths are ordinary nested object fields. Array positions
        # are read-only to prevent accidental modification of source records.
        raise GraphError("target_path_must_be_nested_object_fields")
    current = target
    for part in parts[:-1]:
        current = current.setdefault(part, {})
        if not isinstance(current, dict):
            raise GraphError("conflicting_input_path")
    leaf = parts[-1]
    if leaf in current and current[leaf] != value:
        raise GraphError("two_upstream_nodes_conflict_on_input_path")
    current[leaf] = value


def resolve_node_inputs(graph: dict, run: dict, node_id: str) -> dict:
    structure = validate_graph(graph)
    if node_id not in structure["incoming"]:
        raise GraphError("unknown_node")
    payload = {}
    origin = []
    missing = []
    for edge in structure["incoming"][node_id]:
        source = edge["source"]
        state = run.get("states",{}).get(source,"pending")
        if not _matches(state,edge.get("when","success")):
            continue
        for source_path,target_path in edge.get("mapping",{}).items():
            found,value = _json_path_read(run.get("outputs",{}).get(source),source_path)
            if not found:
                missing.append({"source":source,"source_path":source_path,
                                "target_path":target_path})
                continue
            _json_path_write(payload,target_path,value)
            origin.append({"from_node":source,"source_path":source_path,
                           "target_path":target_path})
    return {"values":payload,"lineage":origin,"missing_paths":missing,
            "test_only":True}


def new_debug_run(graph: dict) -> dict:
    valid = validate_graph(graph, publish=True)
    start = valid["start_id"]
    return {
        "status":"paused","mode":"simulation",
        "states":{node["id"]:("succeeded" if node["id"]==start else "pending")
                  for node in graph["nodes"]},
        "outputs":{start:{"origin":"selected_tender_reference",
                          "note":"Original G2B values are resolved by existing official node APIs"}},
        "fixtures":{}, "breakpoints":[],
        "events":[{"action":"start","node_id":start}],
        "steps_completed":0, "paused_at":None,
        "no_real_collector_executed":True,
        "automatic_bid_submission":False,
    }


def _append(run: dict, action: str, node_id: str | None = None, **details) -> dict:
    r = deepcopy(run)
    event = {"action":action,"node_id":node_id,**details}
    r.setdefault("events",[]).append(event)
    r["events"] = r["events"][-300:]
    return r


def _simulate_execute(graph: dict, run: dict, node_id: str, ignore_before: bool = False) -> dict:
    node = next((n for n in graph["nodes"] if n["id"] == node_id), None)
    if not node:
        raise GraphError("unknown_node")
    permitted = runnable_nodes(graph, run)["ready"]
    if node_id not in permitted:
        raise GraphError("selected_node_dependencies_not_satisfied")
    r = deepcopy(run)
    r.setdefault("inputs",{})[node_id] = resolve_node_inputs(graph,r,node_id)
    if r["inputs"][node_id]["missing_paths"]:
        r["status"]="paused"
        r["paused_at"]=node_id
        return _append(r,"missing_upstream_mapped_input",node_id,
                       missing=r["inputs"][node_id]["missing_paths"])
    if node.get("breakpoint_before") and not ignore_before:
        r["status"] = "paused"
        r["paused_at"] = node_id
        return _append(r,"breakpoint_before",node_id)
    if node["type"] in ("end","join","note","start"):
        output = {"node_type":node["type"],"simulation":True}
    else:
        fixture = r.get("fixtures",{}).get(node_id)
        if not isinstance(fixture, dict) or "output" not in fixture:
            r["status"] = "paused"
            r["paused_at"] = node_id
            return _append(r,"input_fixture_required",node_id,
                           reason="Supply explicit test output before stepping this feature")
        if fixture.get("fail"):
            r["states"][node_id] = "failed"
            r["outputs"][node_id] = {"error":fixture.get("error","simulated_failure"),
                                     "test_only":True}
            r["steps_completed"] += 1
            r["paused_at"] = None
            return _append(r,"node_failed_simulated",node_id)
        output = fixture["output"]
    r["states"][node_id] = "succeeded"
    r["outputs"][node_id] = output
    r["steps_completed"] += 1
    r["paused_at"] = node_id if node.get("breakpoint_after") else None
    r["status"] = "paused"
    if all(state in TERMINAL for state in r["states"].values()):
        r["status"] = "completed"
    return _append(r,"node_succeeded_simulated",node_id,
                   breakpoint_after=bool(node.get("breakpoint_after")))


def debug_action(graph: dict, run: dict, action: str, node_id: str | None = None,
                 payload: Any = None) -> dict:
    validate_graph(graph, publish=True)
    if action == "stop":
        r = _append(run,"stop")
        r["status"] = "cancelled"
        for key,state in r["states"].items():
            if state in ("pending","ready"):r["states"][key]="cancelled"
        return r
    if run["status"] in ("cancelled","completed") and action not in ("restart",):
        raise GraphError("debug_run_is_terminal")
    if action == "pause":
        r = _append(run,"pause")
        r["status"] = "paused"
        return r
    if action == "resume":
        r = _append(run,"resume")
        r["status"] = "ready"
        r["paused_at"] = None
        return r
    if action == "pin":
        if not node_id or node_id not in run["states"]:
            raise GraphError("unknown_node")
        r = _append(run,"test_output_pinned",node_id)
        r.setdefault("fixtures",{})[node_id] = {"output":payload, "source":"manual_test_pin"}
        return r
    if action == "fail":
        if not node_id or node_id not in run["states"]:
            raise GraphError("unknown_node")
        r = _append(run,"test_failure_injected",node_id)
        r.setdefault("fixtures",{})[node_id] = {"output":None, "fail":True,
                        "error":str(payload or "simulated_failure")[:200]}
        return r
    if action in ("skip","retry"):
        if not node_id or node_id not in run["states"]:
            raise GraphError("unknown_node")
        if node_id == next(n["id"] for n in graph["nodes"] if n["type"] == "start"):
            raise GraphError("cannot_skip_or_retry_tender_start")
        r = deepcopy(run)
        if action == "skip":
            if node_id not in runnable_nodes(graph,r)["ready"]:
                raise GraphError("node_is_not_runnable")
            r["states"][node_id] = "skipped"
            r["outputs"].pop(node_id,None)
        else:
            if r["states"][node_id] not in TERMINAL:
                raise GraphError("retry_requires_terminal_node")
            r["states"][node_id] = "pending"
            r["outputs"].pop(node_id,None)
            # Any descendants already executed rely on an invalidated output;
            # clear their state for safe deterministic replay.
            neighbours=validate_graph(graph)["neighbours"]
            stack=list(neighbours[node_id])
            while stack:
                child=stack.pop()
                r["states"][child]="pending"
                r["outputs"].pop(child,None)
                stack.extend(neighbours[child])
        r["status"]="paused"
        return _append(r,action,node_id)
    if action == "step":
        if node_id is None:
            available = runnable_nodes(graph,run)["ready"]
            if not available:
                raise GraphError("no_ready_nodes_to_step")
            node_id = available[0]
        return _simulate_execute(graph,run,node_id,ignore_before=True)
    if action == "continue":
        r = deepcopy(run)
        r["status"]="ready"
        for _ in range(30):
            available = runnable_nodes(graph,r)["ready"]
            if not available:break
            nxt = available[0]
            outcome = _simulate_execute(graph,r,nxt,ignore_before=False)
            r=outcome
            if r.get("paused_at") or r["status"]=="completed":break
        else:
            raise GraphError("simulation_step_limit_reached")
        r["status"] = "paused" if r["status"] != "completed" else "completed"
        return r
    raise GraphError("unsupported_debug_action")


def preview_run(graph: dict, run: dict) -> dict:
    active = runnable_nodes(graph,run)
    return {
        "status":run["status"],"ready_nodes":active["ready"],
        "blocked_nodes":active["blocked"],"waiting_nodes":active["waiting"],
        "parallel_ready":active["simulated_parallel_ready"],
        "node_states":run["states"],"outputs":run["outputs"],
        "resolved_inputs":run.get("inputs",{}),
        "events":run.get("events",[]), "paused_at":run.get("paused_at"),
        "steps_completed":run.get("steps_completed",0),
        "simulation_only":True,"actual_worker_parallelism_verified":False,
        "bid_submission_performed":False,
    }
