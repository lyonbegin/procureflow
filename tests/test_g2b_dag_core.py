"""Real graph-rule unit tests: sequential/parallel, all/any/quorum, source files
and isolated step-debugger controls. The production Worker is never invoked."""
from copy import deepcopy
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from g2b_dag_core import (
    starter_graph,validate_graph,GraphError,runnable_nodes,new_debug_run,
    debug_action,preview_run,
)
from g2b_dag_api import router


class EditableDAGTest(unittest.TestCase):
    def setUp(self):
        self.graph=starter_graph()
        self.run=new_debug_run(self.graph)

    def test_starter_is_connected_dag_with_one_tender_source(self):
        result=validate_graph(self.graph,publish=True)
        self.assertEqual(result["start_id"],"tender")
        self.assertEqual(len(result["topological_order"]),len(self.graph["nodes"]))
        self.assertEqual(len(self.graph["edges"]),9)

    def test_missing_unknown_or_duplicate_nodes_rejected(self):
        graph=deepcopy(self.graph)
        graph["nodes"][1]["id"]="tender"
        with self.assertRaises(GraphError):validate_graph(graph)
        graph=deepcopy(self.graph)
        graph["edges"][0]["target"]="unknown"
        with self.assertRaises(GraphError):validate_graph(graph)

    def test_cycle_and_self_link_rejected(self):
        graph=deepcopy(self.graph)
        graph["edges"].append({"id":"loop", "source":"finish","target":"history"})
        with self.assertRaises(GraphError):validate_graph(graph)
        graph=deepcopy(self.graph)
        graph["edges"][0]["target"]=graph["edges"][0]["source"]
        with self.assertRaises(GraphError):validate_graph(graph)

    def test_editable_draft_can_be_disconnected_but_published_cannot(self):
        graph=deepcopy(self.graph)
        graph["edges"]=[e for e in graph["edges"] if e["target"]!="eligibility"]
        validate_graph(graph)
        with self.assertRaises(GraphError):validate_graph(graph,publish=True)

    def test_safe_mapping_paths_and_quorum_validation(self):
        graph=deepcopy(self.graph)
        graph["edges"][0]["mapping"]={"output.price":"input.price"}
        validate_graph(graph)
        graph["edges"][0]["mapping"]={"output.price":"__import__('os').system('rm -rf /')"}
        with self.assertRaises(GraphError):validate_graph(graph)
        graph=deepcopy(self.graph)
        next(n for n in graph["nodes"] if n["id"]=="join")["join"]={"mode":"quorum","minimum":4}
        with self.assertRaises(GraphError):validate_graph(graph,publish=True)

    def test_start_refuses_any_edge_or_extra_start(self):
        graph=deepcopy(self.graph)
        graph["edges"][0]["target"]="tender"
        with self.assertRaises(GraphError):validate_graph(graph)
        graph=deepcopy(self.graph)
        graph["nodes"][1]["type"]="start"
        with self.assertRaises(GraphError):validate_graph(graph)

    def test_first_ready_node_is_notice_after_tender(self):
        self.assertEqual(runnable_nodes(self.graph,self.run)["ready"],["notice"])
        r=debug_action(self.graph,self.run,"step")
        self.assertEqual(r["paused_at"],"notice")
        self.assertIn("input_fixture_required",str(r["events"][-1]))
        self.assertEqual(r["states"]["notice"],"pending")

    def _complete_notice(self):
        r=debug_action(self.graph,self.run,"pin","notice",{"original_verified":True})
        r=debug_action(self.graph,r,"step","notice")
        return r

    def test_independent_hist_doc_eligibility_ready_in_parallel(self):
        r=self._complete_notice()
        self.assertEqual(set(runnable_nodes(self.graph,r)["ready"]),
                         {"history","documents","eligibility"})
        self.assertTrue(runnable_nodes(self.graph,r)["simulated_parallel_ready"])

    def test_all_join_waits_for_every_required_branch(self):
        r=self._complete_notice()
        for name in ("history","documents"):
            r=debug_action(self.graph,r,"pin",name,{"test":True})
            r=debug_action(self.graph,r,"step",name)
        self.assertIn("join",runnable_nodes(self.graph,r)["waiting"])
        r=debug_action(self.graph,r,"pin","eligibility",{"ready":True})
        r=debug_action(self.graph,r,"step","eligibility")
        self.assertIn("join",runnable_nodes(self.graph,r)["ready"])

    def test_any_join_passes_after_one_success(self):
        graph=deepcopy(self.graph)
        next(n for n in graph["nodes"] if n["id"]=="join")["join"]={"mode":"any"}
        r=self._complete_notice()
        r=debug_action(graph,r,"pin","documents",{"parsed":True})
        r=debug_action(graph,r,"step","documents")
        self.assertIn("join",runnable_nodes(graph,r)["ready"])

    def test_quorum_two_out_of_three(self):
        graph=deepcopy(self.graph)
        next(n for n in graph["nodes"] if n["id"]=="join")["join"]={"mode":"quorum","minimum":2}
        r=self._complete_notice()
        for n in ("documents","history"):
            r=debug_action(graph,r,"pin",n,{"mock":n})
            r=debug_action(graph,r,"step",n)
        self.assertIn("join",runnable_nodes(graph,r)["ready"])

    def test_failure_cannot_satisfy_all_required_inputs(self):
        r=self._complete_notice()
        r=debug_action(self.graph,r,"fail","history","simulated_503")
        r=debug_action(self.graph,r,"step","history")
        for n in ("documents","eligibility"):
            r=debug_action(self.graph,r,"pin",n,{"status":"success"})
            r=debug_action(self.graph,r,"step",n)
        self.assertIn("join",runnable_nodes(self.graph,r)["blocked"])
        self.assertNotIn("join",runnable_nodes(self.graph,r)["ready"])

    def test_replay_clears_descendants_after_retry(self):
        r=self._complete_notice()
        r=debug_action(self.graph,r,"fail","history",503)
        r=debug_action(self.graph,r,"step","history")
        self.assertEqual(r["states"]["history"],"failed")
        r=debug_action(self.graph,r,"retry","history")
        self.assertEqual(r["states"]["history"],"pending")
        self.assertNotIn("history",r["outputs"])

    def test_breakpoint_before_after_and_step_override(self):
        graph=deepcopy(self.graph)
        next(n for n in graph["nodes"] if n["id"]=="notice")["breakpoint_before"]=True
        r=debug_action(graph,self.run,"pin","notice",{"passed":True})
        r=debug_action(graph,r,"continue")
        self.assertEqual(r["paused_at"],"notice")
        self.assertEqual(r["states"]["notice"],"pending")
        r=debug_action(graph,r,"step","notice")
        self.assertEqual(r["states"]["notice"],"succeeded")

    def test_manual_skip_does_not_forge_success(self):
        r=self._complete_notice()
        r=debug_action(self.graph,r,"skip","history")
        self.assertEqual(r["states"]["history"],"skipped")
        self.assertNotIn("history",r["outputs"])
        self.assertFalse(preview_run(self.graph,r)["bid_submission_performed"])

    def test_stop_cancels_pending_and_rejects_more_steps(self):
        stopped=debug_action(self.graph,self.run,"stop")
        self.assertEqual(stopped["status"],"cancelled")
        with self.assertRaises(GraphError):debug_action(self.graph,stopped,"step")

    def test_every_executed_output_is_marked_test_only_or_explicit(self):
        r=self._complete_notice()
        self.assertTrue(r["no_real_collector_executed"])
        self.assertFalse(r["automatic_bid_submission"])
        view=preview_run(self.graph,r)
        self.assertTrue(view["simulation_only"])
        self.assertFalse(view["actual_worker_parallelism_verified"])


class DAGRouteContracts(unittest.TestCase):
    def test_expected_authenticated_routes_registered(self):
        app=FastAPI()
        app.include_router(router)
        paths={x.path: x.methods for x in app.routes}
        self.assertIn("POST",paths["/api/g2b/cases/{bid_no}/workflow/designs"])
        self.assertIn("GET",paths["/api/g2b/cases/{bid_no}/workflow/designs"])
        self.assertIn("PUT",paths["/api/g2b/cases/{bid_no}/workflow/designs/{workflow_id}"])
        self.assertIn("DELETE",paths["/api/g2b/cases/{bid_no}/workflow/designs/{workflow_id}"])
        self.assertIn("POST",paths["/api/g2b/cases/{bid_no}/workflow/debug-runs/{run_id}/actions"])


if __name__=="__main__":
    unittest.main()
