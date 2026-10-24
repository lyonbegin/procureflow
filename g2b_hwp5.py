"""HWP 5.x paragraph text extractor for genuine OLE HWP binaries."""
import io
import re
import zlib
import struct

def extract_hwp5(raw, max_text=800000):
    try:
        import olefile
        stream=io.BytesIO(raw)
        if not olefile.isOleFile(stream):
            return "hwp_not_ole5",""
        with olefile.OleFileIO(io.BytesIO(raw)) as ole:
            if not ole.exists("FileHeader"):
                return "hwp_missing_file_header",""
            header=ole.openstream("FileHeader").read()
            if len(header)<40 or b"HWP Document File" not in header[:36]:
                return "hwp_invalid_file_header",""
            flags=struct.unpack_from("<I",header,36)[0]
            if flags & 2:return "hwp_encrypted",""
            sections=[p for p in ole.listdir()
                      if len(p)==2 and p[0]=="BodyText"
                      and re.fullmatch(r"Section[0-9]+",p[1])]
            parts=[]
            for path in sorted(sections,key=lambda p:int(p[1][7:])):
                body=ole.openstream(path).read()
                if flags & 1:
                    try:body=zlib.decompress(body,-15)
                    except zlib.error:
                        try:body=zlib.decompress(body)
                        except zlib.error:return "hwp_invalid_compression",""
                index=0
                while index+4<=len(body):
                    header=struct.unpack_from("<I",body,index)[0]
                    index+=4
                    tag=header&1023
                    length=(header>>20)&4095
                    if length==4095:
                        if index+4>len(body):break
                        length=struct.unpack_from("<I",body,index)[0]
                        index+=4
                    if index+length>len(body):break
                    item=body[index:index+length]
                    index+=length
                    if tag==67:
                        value=item.decode("utf-16-le","ignore")
                        value="".join(ch if ord(ch)>=32 or ch in "\\n\\r\\t"
                                      else " " for ch in value)
                        value=re.sub(r" {3,}","  ",value).strip()
                        if value:parts.append(value)
                    if sum(len(t) for t in parts)>max_text:break
                if sum(len(t) for t in parts)>max_text:break
            result="\\n".join(parts)[:max_text]
            if len(result)<40 or not re.search(r"[가-힣]{2,}",result):
                return "hwp_text_not_decoded",result
            return "parsed",result
    except Exception as exc:
        return "hwp_parse_"+type(exc).__name__,""
