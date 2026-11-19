import json
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
