"""N02 all-original-file download, safe durable folders and manifest tests."""
import json
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.parse import parse_qs,urlparse,quote
from unittest.mock import patch
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"n8n/unified"))
import n02_collect as n02

BID="R26BK01816186"
NOTICE={"bid_no":BID,"bid_ord":"000","business_code":"22",
        "title":"실제 공고","agency":"실제 기관"}

class FakeResponse:
    def __init__(self,body,filename):
        self.status=200
        self._file=BytesIO(body)
        self.headers={
          "Content-Type":"application/octet-stream",
          "Content-Length":str(len(body)),
          "Content-Disposition":"attachment;filename="+quote(filename)}
    def read(self,n=-1):return self._file.read(n)
    def __enter__(self):return self
    def __exit__(self,*args):self._file.close()

class FakeOfficial:
    def __init__(self,files,error_at=None):
        self.files=files
        self.error_at=error_at
        self.queried=[]
    def open(self,request,timeout=None):
        url=request.full_url
        assert url.startswith(n02.DOWNLOAD+"?")
        query=parse_qs(urlparse(url).query)
        assert query["bidPbancNo"]==[BID]
        assert query["bidPbancOrd"]==["000"]
        assert query["prcmBsneSeCd"]==["22"]
        seq=int(query["fileSeq"][0])
        self.queried.append(seq)
        if self.error_at==seq:
            raise HTTPError(url,503,"unavailable",{},None)
        if seq not in self.files:
            raise HTTPError(url,422,"Unprocessable Entity",{},None)
        filename,body=self.files[seq]
        return FakeResponse(body,filename)

class N02Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p=patch.object(n02,"STORAGE_ROOT",Path(self.tmp.name)/"bids")
        p.start()
        self.addCleanup(p.stop)
    def fake(self):
        return FakeOfficial({
          1:("별지서식.hwp",b"\xd0\xcf\x11\xe0"+b"one"),
          2:("입찰지침서.pdf",b"%PDF-1.5"+b"two"),
          3:("입찰공고.pdf",b"%PDF-1.6"+b"three"),
        })
    def test_collects_every_file_not_only_first_two_and_saves_manifest(self):
        official=self.fake()
        report=n02.collect(official,NOTICE)
        self.assertEqual(official.queried,[1,2,3,4,5,6])
        self.assertEqual(report["file_count"],3)
        self.assertEqual(report["downloaded"],3)
        self.assertTrue(report["official_attachment_inventory_complete"])
        self.assertTrue(report["end_of_sequence_confirmed"])
        self.assertFalse(report["analysis_performed"])
        self.assertEqual(report["file_names"],["별지서식.hwp","입찰지침서.pdf","입찰공고.pdf"])
        self.assertEqual(report["file_types"],["hwp","pdf","pdf"])
        folder=Path(report["storage_folder"])
        self.assertEqual(len(list(folder.iterdir())),3)
        stored=json.loads(Path(report["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(stored["file_names"],report["file_names"])
        self.assertEqual(stored["notice_bid_no"],BID)
        self.assertEqual(stored["notice_bid_ord"],"000")
        for file in report["files"]:
            target=Path(file["saved_path"])
            self.assertTrue(target.exists())
            self.assertEqual(target.parent,folder)
            import hashlib
            self.assertEqual(file["sha256"],hashlib.sha256(target.read_bytes()).hexdigest())
            self.assertTrue(file["filename_from_official_header"])
    def test_fourth_file_is_not_skipped_even_if_first_three_already_exist(self):
        files=self.fake().files
        files[4]=("공내역서.xlsx",b"PK\x03\x04"+b"xlsx")
        report=n02.collect(FakeOfficial(files),NOTICE)
        self.assertEqual(report["file_count"],4)
        self.assertEqual(report["files"][3]["file_type"],"xlsx")
        self.assertTrue(Path(report["files"][3]["saved_path"]).exists())
        self.assertTrue(report["official_attachment_inventory_complete"])
    def test_repeated_same_name_is_saved_without_collision(self):
        files={1:("공고.pdf",b"%PDF-1.4A"),2:("공고.pdf",b"%PDF-1.4B")}
        report=n02.collect(FakeOfficial(files),NOTICE)
        self.assertEqual(report["file_count"],2)
        self.assertNotEqual(report["files"][0]["saved_path"],report["files"][1]["saved_path"])
        self.assertNotEqual(Path(report["files"][0]["saved_path"]).read_bytes(),
                            Path(report["files"][1]["saved_path"]).read_bytes())
    def test_directory_traversal_in_filename_is_neutralized(self):
        path=n02._safe_name("../../other/../공고.pdf")
        self.assertEqual(path,"공고.pdf")
        official=FakeOfficial({1:("../../admin/evil.pdf",b"%PDF-1.4")})
        report=n02.collect(official,NOTICE)
        self.assertEqual(Path(report["files"][0]["saved_path"]).parent,Path(report["storage_folder"]))
    def test_http_503_fails_closed_and_keeps_saved_first_file(self):
        official=self.fake()
        official.error_at=2
        report=n02.collect(official,NOTICE)
        self.assertFalse(report["official_attachment_inventory_complete"])
        self.assertEqual(report["file_count"],1)
        self.assertEqual(report["errors"][0]["file_seq"],2)
        self.assertTrue(Path(report["manifest_path"]).exists())
    def test_final_handoff_reads_disk_and_verifies_all_original_hashes(self):
        report=n02.collect(self.fake(),NOTICE)
        handoff=n02.verify_saved_files(report)
        self.assertTrue(handoff["original_files_integrity_verified"])
        self.assertEqual(handoff["verified_saved_original_count"],3)
        self.assertFalse(handoff["content_analysis_performed"])
        Path(report["files"][1]["saved_path"]).write_bytes(b"%PDF-TAMPERED")
        with self.assertRaisesRegex(ValueError,"BYTES_MISMATCH|SHA256_MISMATCH"):
            n02.verify_saved_files(report)

    def test_missing_gap_not_marked_complete(self):
        official=FakeOfficial({1:("첫번째.hwp",b"\xd0\xcf\x11\xe0A"),
                               3:("세번째.pdf",b"%PDF-1.4B")})
        report=n02.collect(official,NOTICE)
        self.assertEqual(report["file_count"],2)
        self.assertIn(2,report["unexpected_missing_indices"])
        self.assertFalse(report["official_attachment_inventory_complete"])
    def test_missing_all_files_not_marked_success(self):
        report=n02.collect(FakeOfficial({}),NOTICE)
        self.assertEqual(report["file_count"],0)
        self.assertFalse(report["official_attachment_inventory_complete"])
        self.assertTrue(Path(report["manifest_path"]).exists())
    def test_manifest_path_must_match_tender_and_storage_root(self):
        official=self.fake()
        report=n02.collect(official,NOTICE)
        loaded=n02.read_manifest(report["manifest_path"],NOTICE)
        self.assertEqual(loaded["file_count"],3)
        with self.assertRaisesRegex(ValueError,"NOTICE_MISMATCH"):
            n02.read_manifest(report["manifest_path"],{**NOTICE,"bid_no":"R26BK01787028"})
        with self.assertRaisesRegex(ValueError,"OUTSIDE_STORAGE"):
            n02.read_manifest("/tmp/not-our-manifest.json",NOTICE)
    def test_non_official_identity_rejected_before_io(self):
        with self.assertRaisesRegex(ValueError,"NOTICE_ID_INVALID"):
            n02.collect(self.fake(),{**NOTICE,"bid_no":"../etc/passwd"})

if __name__=="__main__":unittest.main()
