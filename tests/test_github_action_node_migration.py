"""Production boundary: all nine jobs on GitHub; Railway only dispatch+storage."""
import base64,hashlib,json,os,sys,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"n8n/unified"))
import github_actions_bridge as bridge
import github_node_worker as worker
import github_oidc as auth
import n01_auto,n02_collect
BID="R26BK01816186"
NOTICE={"bid_no":BID,"bid_ord":"000","title":"공식 공고",
        "agency":"공식 발주기관","source":"https://www.g2b.go.kr",
        "official_fields_verified":True,"search_request_verified":True,
        "notice_list":"AVAILABLE","selection_reason":"newest_unprocessed"}
CLAIMS={"run_id":"999444","repository":"lyonbegin/procureflow"}

class MigrationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory()
  self.addCleanup(self.tmp.cleanup)
  for module,key,value in [
    (bridge,"ROOT",Path(self.tmp.name)/"actions"),
    (bridge,"STORAGE_ROOT",Path(self.tmp.name)/"originals"),
    (n01_auto,"LEDGER_PATH",Path(self.tmp.name)/"n01-progress.json")]:
   p=patch.object(module,key,value)
   p.start();self.addCleanup(p.stop)
  environment=patch.dict(os.environ,{"PROCUREFLOW_GITHUB_DISPATCH_TOKEN":"unit-test-not-real"})
  environment.start();self.addCleanup(environment.stop)
  authmock=patch.object(bridge,"verify",return_value=CLAIMS)
  authmock.start();self.addCleanup(authmock.stop)
  self.dispatched=[]
  def send(run,stage):
   self.dispatched.append((run["run_id"],stage))
   return {"stage":stage,"requested_at":"unit-test","method":"workflow_dispatch"}
  dispatch=patch.object(bridge,"_dispatch",side_effect=send)
  dispatch.start();self.addCleanup(dispatch.stop)
  self.cookie="unit-test-cookie"
  self.run=bridge.begin(self.cookie,{"mode":"auto"})
  self.rid=self.run["run_id"]
 def _result(self,stage,status,output,inputs=None):
  return bridge.receive("Bearer fake-oidc-in-test",{
    "run_id":self.rid,"stage":stage,"status":status,
    "input":inputs or {"stage":stage},"output":output,
    "github_run_id":"999444"})
 def test_only_dispatches_first_node_no_railway_python_runner(self):
  self.assertEqual(self.dispatched,[(self.rid,"N01")])
  state=bridge.current(self.cookie)
  self.assertEqual(state["active_node"],"N01")
  self.assertEqual(state["mode"],"github_actions_nine_nodes")
  self.assertNotIn("uploads",state)
  source=(ROOT/"n8n/unified/patch-server.py").read_text(encoding="utf-8")
  self.assertIn("github_actions_bridge.begin(sid,body)",source)
  self.assertNotIn("live_nine_test.begin(sid,body)",source)
  self.assertNotIn("Thread(target=_execute",source)
 def test_missing_dispatch_credentials_never_falls_back_to_railway(self):
  with patch.dict(os.environ,{"PROCUREFLOW_GITHUB_DISPATCH_TOKEN":""}):
   with self.assertRaisesRegex(RuntimeError,"GITHUB_DISPATCH_TOKEN_NOT_CONFIGURED"):
    bridge.begin("second-cookie",{"mode":"auto"})
  self.assertEqual(len(self.dispatched),1)
 def test_authenticated_per_node_results_preserve_blocked_statuses(self):
  self._result("N01","verified",dict(NOTICE))
  self.assertEqual(self.dispatched[-1][1],"N02")
  context=bridge.context("Bearer test",self.rid,"N02")
  self.assertEqual(context["selected_notice"]["bid_no"],BID)
  self.assertEqual(context["stage"],"N02")
  self._result("N02","partial",{"file_count":0,"files":[],
      "official_attachment_inventory_complete":False})
  status={"N03":"partial","N04":"partial","N05":"blocked",
          "N06":"blocked","N07":"blocked","N08":"partial","N09":"partial"}
  for key in [f"N{i:02d}" for i in range(3,10)]:
   extra={"source_query_verified":True,"matching_selected_notice":0} if key=="N04" else {"reason":key+"_NOT_COMPLETE"}
   if key=="N09":extra["N02_persistent_file_handoff"]={"original_files_integrity_verified":False}
   self._result(key,status[key],extra)
  state=bridge.current(self.cookie)
  self.assertEqual(state["completed_steps"],9)
  self.assertEqual(state["status"],"completed_with_missing_evidence")
  self.assertEqual(len(self.dispatched),9)
  self.assertEqual([stage for _,stage in self.dispatched],list(worker.STAGES))
  self.assertEqual(len([s for s in state["steps"] if s["status"]=="verified"]),1)
  self.assertEqual(len([s for s in state["steps"] if s["status"]=="blocked"]),3)
  self.assertEqual(n01_auto._load()["records"][BID+"-000"]["state"],"incomplete")
  self.assertEqual(state["steps"][8]["github_run_id"],"999444")
 def test_second_browser_cannot_select_same_notice_while_first_is_running(self):
  with self.assertRaisesRegex(ValueError,"LIVE_RUN_ALREADY_ACTIVE"):
   bridge.begin("another-browser",{"mode":"auto"})
  self.assertEqual(len(self.dispatched),1)
  self.assertEqual(bridge.current(self.cookie)["active_node"],"N01")
 def test_audit_is_read_only_oidc_bound_and_aggregate_only(self):
  selected=dict(NOTICE)
  selected["private_company_document"]="DO_NOT_EXPOSE"
  self._result("N01","verified",selected)
  summary=bridge.audit("Bearer github-oidc",self.rid)
  self.assertEqual(summary["completed_steps"],1)
  self.assertEqual(summary["stages"][0]["node"],"N01")
  self.assertEqual(summary["stages"][0]["details"]["selected_bid_no"],BID)
  self.assertNotIn("private_company_document",str(summary))
  self.assertFalse(summary["contains_raw_company_documents"])
  with patch.object(bridge,"verify",side_effect=auth.GitHubOIDCError("INVALID_OIDC")):
   with self.assertRaises(auth.GitHubOIDCError):
    bridge.audit("Bearer invalid",self.rid)
 def test_stage_order_and_duplicate_callback_are_rejected(self):
  with self.assertRaisesRegex(ValueError,"ACTION_NOT_PENDING_FOR_RUN"):
   self._result("N02","verified",{})
  self._result("N01","verified",dict(NOTICE))
  with self.assertRaisesRegex(ValueError,"ACTION_NOT_PENDING_FOR_RUN"):
   self._result("N01","verified",dict(NOTICE))
 def test_binary_origin_upload_sha_manifest_and_integrity(self):
  self._result("N01","verified",dict(NOTICE))
  body=b"%PDF-1.4 real original bytes for test"
  name="입찰공고.pdf"
  digest=hashlib.sha256(body).hexdigest()
  headers={"X-Procureflow-Run":self.rid,
   "X-Procureflow-Stage":"N02","X-Procureflow-File-Seq":"1",
   "X-Procureflow-Chunk":"0",
   "X-Procureflow-File-Name":base64.urlsafe_b64encode(name.encode()).decode(),
   "X-Procureflow-File-Size":str(len(body)),
   "X-Procureflow-File-Sha256":digest}
  saved=bridge.upload("Bearer unit-test-oidc",headers,body)
  self.assertTrue(saved["saved"])
  output={"file_count":1,"files":[{"file_seq":1,"original_filename":name,
         "size_bytes":len(body),"sha256":digest,"file_type":"pdf"}],
          "official_attachment_inventory_complete":True,
          "analysis_performed":False}
  self._result("N02","verified",output)
  record=bridge.current(self.cookie)["steps"][1]["output"]
  self.assertTrue(record["persisted_on_railway"])
  self.assertEqual(record["file_count"],1)
  self.assertTrue(Path(record["manifest_path"]).exists())
  self.assertEqual(Path(record["files"][0]["saved_path"]).read_bytes(),body)
  # The selected N03 collection job can read official N02 bytes without
  # evaluating bidder eligibility; all other intermediate stages are denied.
  source_for_n03=bridge.original("Bearer unit-test-oidc",self.rid,1)
  self.assertEqual(source_for_n03.read_bytes(),body)
  self._result("N03","partial",{"detail10_verified":False,
    "business_evaluation_performed":False})
  with self.assertRaisesRegex(ValueError,"ORIGINAL_READ_STAGE_NOT_AUTHORIZED"):
   bridge.original("Bearer unit-test-oidc",self.rid,1)
  for i in range(4,9):self._result(f"N{i:02d}","partial",{"reason":"held"})
  original=bridge.original("Bearer unit-test-oidc",self.rid,1)
  self.assertEqual(original.read_bytes(),body)
  self._result("N09","partial",{"N02_persistent_file_handoff":{
    "original_files_integrity_verified":True,"verified_saved_original_count":1}})
  self.assertEqual(bridge.current(self.cookie)["status"],"completed_with_missing_evidence")
 def test_chrome_not_in_production_image_and_actions_node_runner(self):
  d=(ROOT/"n8n/Dockerfile.procureflow-unified").read_text()
  wf=(ROOT/".github/workflows/procureflow-node.yml").read_text()
  self.assertNotIn("python -m playwright install",d)
  self.assertNotIn("playwright install --with-deps",wf.lower())
  self.assertIn("id-token: write",wf)
 def test_worker_collects_five_six_seven_without_assessment_or_price(self):
  ctx={"run_id":self.rid,"selected_notice":NOTICE,"outputs":{
    "N01":NOTICE,"N02":{"files":[{"original_filename":"1.hwp","file_seq":1}]},
    "N03":{"detail10_verified":False},"N04":{"records":[]},
    "N05":{"opening_records":[]}}}
  for stage in ("N05","N06","N07"):
   status,inputs,output=worker.execute(stage,ctx)
   self.assertEqual(status,"partial",(stage,output))
   self.assertFalse(output["business_evaluation_performed"])
   self.assertIsNone(output.get("recommended_bid"))
 def test_unauthorized_input_requires_real_oidc(self):
  with patch.object(bridge,"verify",side_effect=auth.GitHubOIDCError("UNAUTHORIZED")):
   with self.assertRaises(auth.GitHubOIDCError):
    bridge.context("Bearer invalid",self.rid,"N01")
  with self.assertRaises(auth.GitHubOIDCError):
   auth.verify("Not Bearer")
if __name__=="__main__":unittest.main()
