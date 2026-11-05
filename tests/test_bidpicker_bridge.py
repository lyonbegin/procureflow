import os
import unittest
import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from integrations.bidpicker import bridge as b


SAMPLE = {
    "bidNo": "R26BK01234567", "bidSeq": "001", "title": "격리 연동 테스트",
    "agencyName": "시험기관", "originalUrl": "https://www.g2b.go.kr/a",
}


class FakeResponse:
    def __init__(self, data):
        self.data = json.dumps(data).encode("utf-8")
        self.headers = {"Content-Type": "application/json"}

    def read(self, n):
        return self.data[:n]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class FakeOpener:
    def __init__(self, data):
        self.data = data
        self.request = None

    def open(self, request, timeout=15):
        self.request = request
        return FakeResponse(self.data)


class BridgeTests(unittest.TestCase):
    def test_search_filters(self):
        query = b.Search(keyword="  서버 ", region="서울", task_type="SERVICE", page=2).query()
        self.assertEqual((query["keyword"], query["page"], query["taskType"]), ("서버", "2", "SERVICE"))

    def test_query_bounds(self):
        with self.assertRaises(ValueError):
            b.Search(size=999).query()

    def test_get_uses_authorized_header_and_json(self):
        opener = FakeOpener({"items": [SAMPLE]})
        with patch.dict(os.environ, {"BIDPICKER_USERNAME": "test", "BIDPICKER_PASSWORD": "test"}):
            with patch.object(b, "build_opener", return_value=opener):
                result = b.search_notices(b.Search(keyword="테스트"))
        self.assertEqual(opener.request.get_method(), "GET")
        self.assertTrue(opener.request.get_header("Authorization").startswith("Basic "))
        self.assertEqual(result["items"][0]["bid_seq"], "001")
        self.assertFalse(result["official_evidence_verified"])

    def test_missing_credentials_no_http(self):
        with patch.dict(os.environ, {"BIDPICKER_USERNAME": "", "BIDPICKER_PASSWORD": ""}):
            with patch.object(b, "build_opener") as factory:
                with self.assertRaises(b.SourceUnavailable):
                    b.fetch_json("api/bids")
                factory.assert_not_called()

    def test_mutating_endpoint_rejected(self):
        with self.assertRaises(ValueError):
            b.fetch_json("api/alerts/test")

    def test_unknown_contract_fails_not_empty(self):
        with self.assertRaises(b.DataContractError):
            b.extract_items({"error": "unknown"})
        self.assertEqual(b.extract_items({"data": {"items": [SAMPLE]}}), [SAMPLE])

    def test_missing_bid_sequence_rejected(self):
        with self.assertRaises(b.DataContractError):
            b.normalize_notice({"bidNo": "R1", "title": "title"})

    def test_original_domain_checked(self):
        invalid = b.normalize_notice({**SAMPLE, "originalUrl": "https://fakeg2b.go.kr/"})
        self.assertEqual(invalid["original_url"], "")
        self.assertFalse(invalid["original_url_confirmed_format"])

    def test_sequence_is_key(self):
        first = b.normalize_notice(SAMPLE)
        second = b.normalize_notice({**SAMPLE, "bidSeq": "002"})
        self.assertNotEqual((first["bid_no"], first["bid_seq"]), (second["bid_no"], second["bid_seq"]))
        self.assertEqual(first["hash"], b.normalize_notice(SAMPLE)["hash"])

    def test_independent_db_not_legacy_db(self):
        with patch.dict(os.environ, {"BIDPICKER_DATABASE_URL": "postgresql://host/old",
                                     "DATABASE_URL": "postgresql://host/old"}):
            with self.assertRaisesRegex(RuntimeError, "Independent"):
                b.connect_isolated()

    def test_health_uses_existing_db(self):
        with patch.object(b, "connect_isolated") as connect:
            response = TestClient(b.app).get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["database"], "connected")
            connect.return_value.__enter__.return_value.execute.assert_called_with("SELECT 1")
            self.assertFalse(response.json()["integration_live_verified"])

    def test_health_is_unavailable_without_database(self):
        with patch.object(b, "connect_isolated", side_effect=RuntimeError("Missing database")):
            response = TestClient(b.app).get("/health")
            self.assertEqual(response.status_code, 503)

    def test_auth_required(self):
        with patch.dict(os.environ, {"BIDPICKER_BRIDGE_TOKEN": "good"}):
            with patch.object(b, "search_notices") as read:
                response = TestClient(b.app).get("/api/bidpicker/search")
                self.assertEqual(response.status_code, 401)
                read.assert_not_called()

    def test_sync_disabled_by_default(self):
        with patch.dict(os.environ, {"BIDPICKER_BRIDGE_TOKEN": "good",
                                     "BIDPICKER_SYNC_ENABLED": "0"}):
            with patch.object(b, "sync_notices") as sync:
                response = TestClient(b.app).post("/api/bidpicker/sync",
                    headers={"Authorization": "Bearer good"}, json={})
                self.assertEqual(response.status_code, 409)
                sync.assert_not_called()

    def test_detail_uses_read_only_id(self):
        with patch.dict(os.environ, {"BIDPICKER_BRIDGE_TOKEN": "good"}):
            with patch.object(b, "fetch_json", return_value=SAMPLE) as read:
                response = TestClient(b.app).get("/api/bidpicker/detail/abc-123",
                    headers={"Authorization": "Bearer good"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(read.call_args.args[0], "api/bids/abc-123")
                self.assertFalse(response.json()["official_evidence_verified"])

    def test_detail_rejects_untrusted_id(self):
        with patch.dict(os.environ, {"BIDPICKER_BRIDGE_TOKEN": "good"}):
            with patch.object(b, "fetch_json") as read:
                response = TestClient(b.app).get("/api/bidpicker/detail/bad%20id",
                    headers={"Authorization": "Bearer good"})
                self.assertEqual(response.status_code, 422)
                read.assert_not_called()

    def test_no_legacy_import(self):
        import inspect
        source = inspect.getsource(b)
        self.assertNotIn("from legacy_import", source)
        self.assertNotIn("from db import", source)


class PostgresTests(unittest.TestCase):
    @unittest.skipUnless(os.getenv("BIDPICKER_DATABASE_URL"), "No isolated DB for PostgreSQL tests")
    def test_insert_duplicate_update_and_sequences(self):
        row = b.normalize_notice(SAMPLE)
        with b.connect_isolated() as conn:
            b.ensure_schema(conn)
            conn.execute("TRUNCATE bidpicker_feed.notices")
            self.assertEqual(b.persist_notice(conn, row), "inserted")
            self.assertEqual(b.persist_notice(conn, row), "duplicate")
            revised = b.normalize_notice({**SAMPLE, "title": "수정된 제목"})
            self.assertEqual(b.persist_notice(conn, revised), "updated")
            self.assertEqual(b.persist_notice(conn, b.normalize_notice({**SAMPLE, "bidSeq":"002"})), "inserted")
            count = conn.execute("SELECT count(*) FROM bidpicker_feed.notices").fetchone()[0]
            self.assertEqual(count, 2)
            self.assertFalse(conn.execute(
                "SELECT bool_or(official_evidence_verified) FROM bidpicker_feed.notices").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
