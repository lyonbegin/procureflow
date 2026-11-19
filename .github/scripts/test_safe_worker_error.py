import json
import io
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from safe_worker_error import classify_web2api_failure as classify

class TestSafeWorkerError(unittest.TestCase):
    def test_http_status(self):
        err=urllib.error.HTTPError("https://secret:token@example.com",502,"failure",{},None)
        self.assertEqual(classify(err),"WEB2API_ADAPTER_HTTP_502")
    def test_vendor_500_exposes_safe_error_class_only(self):
        body=json.dumps({"error":{"message":"private text Bearer SECRET token",
                                  "type":"server_error","code":"SendReadinessError"}})
        err=urllib.error.HTTPError("http://127.0.0.1:18080/v1/chat/completions",
              500,"private reason",{},io.BytesIO(body.encode("utf-8")))
        self.assertEqual(classify(err),"WEB2API_VENDOR_SENDREADINESSERROR")
    def test_vendor_500_reports_only_whitelisted_reconciliation_status_and_anchor(self):
        body=json.dumps({"error":{"message":"PRIVATE https://secret.example bearer",
                   "code":"TurnReconciliationError",
                   "subcode":"fetch_failed","anchor_mode":"fresh_chat"}})
        err=urllib.error.HTTPError("http://127.0.0.1:18080",500,"private",{},
              io.BytesIO(body.encode("utf-8")))
        self.assertEqual(classify(err),"WEB2API_VENDOR_TURNRECONCILIATIONERROR_FETCH_FAILED_FRESH_CHAT")

    def test_vendor_500_untrusted_subcode_never_logged(self):
        body=json.dumps({"error":{"message":"PRIVATE CONTENT",
                   "code":"TurnReconciliationError",
                   "subcode":"secret-token","anchor_mode":"fresh_chat"}})
        err=urllib.error.HTTPError("http://127.0.0.1:18080",500,"private",{},
              io.BytesIO(body.encode("utf-8")))
        self.assertEqual(classify(err),"WEB2API_VENDOR_TURNRECONCILIATIONERROR")

    def test_vendor_500_unknown_class_does_not_leak_code_or_message(self):
        body=json.dumps({"error":{"message":"secret prompt",
                                  "code":"SecretTokenBearerUserValue"}})
        err=urllib.error.HTTPError("http://127.0.0.1:18080",
                500,"failure",{},io.BytesIO(body.encode("utf-8")))
        self.assertEqual(classify(err),"WEB2API_ADAPTER_HTTP_500")

    def test_transport_does_not_leak_url(self):
        err=urllib.error.URLError("https://user:password@secret.example/private")
        self.assertEqual(classify(err),"WEB2API_ADAPTER_TRANSPORT")
    def test_json_error(self):
        err=json.JSONDecodeError("private reply","sensitive",0)
        self.assertEqual(classify(err),"WEB2API_RESPONSE_JSON_INVALID")
    def test_unknown_exception_does_not_leak_message(self):
        err=RuntimeError("secret=abc Bearer foo https://secret.example/private")
        self.assertEqual(classify(err),"WEB2API_UNCLASSIFIED_RUNTIMEERROR")
    def test_preserve_known_safe_code(self):
        self.assertEqual(classify(ValueError("WEB2API_CHOICES_MISSING")),"WEB2API_CHOICES_MISSING")
    def test_standard_timeout(self):
        self.assertEqual(classify(TimeoutError("private timeout")), "WEB2API_ADAPTER_TIMEOUT")

if __name__ == "__main__":
    unittest.main()
