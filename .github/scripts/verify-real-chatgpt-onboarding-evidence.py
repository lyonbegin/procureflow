#!/usr/bin/env python3
"""Analyze captured genuine ChatGPT UI hierarchy, never confuse tap with transition."""
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

def check(path):
    root=ET.parse(path).getroot()
    nodes=list(root.iter("node"))
    parents={child:parent for parent in root.iter() for child in parent}
    labels={x for n in nodes for x in
            (n.attrib.get("text","").strip(),n.attrib.get("content-desc","").strip())}
    welcome="Welcome to ChatGPT" in labels
    def clickable(label):
        for n in nodes:
            if label not in (n.attrib.get("text",""), n.attrib.get("content-desc","")):continue
            p=n
            while p is not None:
                a=p.attrib
                if a.get("clickable")=="true" and a.get("enabled")=="true":
                    m=re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",a.get("bounds",""))
                    if m:
                        x1,y1,x2,y2=map(int,m.groups())
                        return [(x1+x2)//2,(y1+y2)//2], [x1,y1,x2,y2]
                p=parents.get(p)
        return None,None
    composer=any(n.attrib.get("editable")=="true" and n.attrib.get("enabled")=="true"
                 for n in nodes)
    point,bounds=clickable("Skip")
    return {
        "screen": "welcome" if welcome else "composer" if composer else "other",
        "welcome_visible":welcome,
        "composer_visible":composer,
        "skip_clickable_ancestor":point is not None,
        "skip_click_point":point,
        "skip_clickable_bounds":bounds,
    }

if __name__=="__main__":
    before=check(Path(sys.argv[1]))
    after=check(Path(sys.argv[2]))
    result={"before":before,"after":after,
            "skip_tap_did_not_exit_welcome":
                before["welcome_visible"] and after["welcome_visible"]}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if len(sys.argv)>3: Path(sys.argv[3]).write_text(json.dumps(result,indent=2))
    if before["skip_clickable_ancestor"] and result["skip_tap_did_not_exit_welcome"]:
        print("CONFIRMED_ONBOARDING_STUCK_AFTER_REPORTED_SKIP_TAP")
    else:
        print("NOT_CONFIRMED_STUCK_OR_EVIDENCE_CHANGED")
