"""Reparse existing original tender files using the installed HWP5 engine."""
from hashlib import sha256
from db import session
from g2b_documents import extract_file

BID="R26BK01787028"
def run():
    with session() as db:
        entries=db.execute("""SELECT file_id,filename,data,sha256
         FROM procureflow.g2b_case_documents
         WHERE bid_no=%s AND data IS NOT NULL ORDER BY file_id""",(BID,)).fetchall()
    result=[]
    for x in entries:
        b=bytes(x["data"])
        if sha256(b).hexdigest()!=x["sha256"]:
            result.append({"id":x["file_id"],"status":"sha_mismatch"});continue
        status,txt=extract_file(x["filename"],b)
        with session() as db:
            db.execute("""UPDATE procureflow.g2b_case_documents
             SET extracted_text=%s,extraction_state=%s
             WHERE bid_no=%s AND file_id=%s""",(txt,status,BID,x["file_id"]))
            db.execute("""UPDATE procureflow.g2b_notice_source_files
             SET state=%s WHERE bid_no=%s AND file_id=%s""",
             (status,BID,x["file_id"]))
        result.append({"id":x["file_id"],"status":status,"chars":len(txt)})
    return {"bid_no":BID,"files_processed":len(result),"result":result}
