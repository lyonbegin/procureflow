#!/usr/bin/env python3
"""Compare *exact* official APK split bytes against the user-uploaded APKM.

Only byte-identical pieces are accepted. The private original is never copied
into the public GitHub repository.
"""
import sys,zipfile,hashlib,json,os
expected={
 "base.apk":"38b17d766429d2ac7aa396f7ae2ec87182b1f581777dbb8f2089f6581458b148",
 "split_config.x86_64.apk":"f556302640b9ea57ebef628c4c729ee3cb94edb3f60ca370cecd9bbd5cc8d112",
 "split_config.xxhdpi.apk":"4d861ef027d3d150a005cea1996cca27801eccd84efc8f38312033c0941d291e",
 "split_config.ko.apk":"5f65c6d5c6ade48974c08e0909fd96a9dfbe8d00029bfe3e26c259cac0aa9edf",
 "split_config.en.apk":"2648e8a6aba7f4158c2e772c31049f7048862998298a583070dea4c2b222e15d",
}
if len(sys.argv)!=2: print("usage: check-chatgpt-variant.py <apkm>",file=sys.stderr);sys.exit(2)
path=sys.argv[1]
try:
 with zipfile.ZipFile(path) as f:
  for name,sha in expected.items():
   candidates=[n for n in f.namelist() if n==name or n.endswith("/"+name)]
   if len(candidates)!=1:
    print(f"MISSING_OR_MULTIPLE {name}",file=sys.stderr);sys.exit(3)
   digest=hashlib.sha256(f.read(candidates[0])).hexdigest()
   if digest!=sha:
    print(f"WRONG_SPLIT_SHA256 {name} {digest[:16]}",file=sys.stderr);sys.exit(4)
 print(json.dumps({"verified":True,"matched_splits":list(expected),"archive":os.path.basename(path)}))
except (OSError,zipfile.BadZipFile,EOFError) as err:
 print("BAD_ARCHIVE",str(err),file=sys.stderr);sys.exit(5)
