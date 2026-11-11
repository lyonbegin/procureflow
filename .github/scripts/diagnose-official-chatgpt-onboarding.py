#!/usr/bin/env python3
"""Forensic classification of REAL official ChatGPT Android onboarding screenshots.

Consumes previously captured Android UI XML and PNG evidence, never mocks
a ChatGPT reply or declares a message/file relay successful.
"""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
import struct
import zlib


def elements(path):
    root = ET.parse(path).getroot()
    nodes = root.findall(".//node")
    return nodes


def describe(path):
    nodes = elements(path)
    texts = [n.attrib.get("text", "").strip() for n in nodes if n.attrib.get("text", "").strip()]
    return {
        "file": str(path),
        "welcome_visible": "Welcome to ChatGPT" in texts,
        "skip_visible": "Skip" in texts,
        "composer_visible": any(
            n.attrib.get("class", "").endswith("EditText") and
            n.attrib.get("enabled") == "true" for n in nodes
        ),
        "new_chat_visible": any("new chat" in s.lower() for s in texts),
        "texts": texts[:16],
    }


def png_body_hash(path):
    """Hash RGB pixels below the status bar, with pure stdlib PNG decoding.

    Artifacts come from adb screencap PNG (noninterlaced RGB/RGBA).
    This avoids comparing changing Android status clock and Wi-Fi indicators.
    """
    import hashlib
    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    offset = 8
    pixels = bytearray()
    width = height = colour = depth = None
    while offset < len(data):
        n = struct.unpack(">I", data[offset:offset+4])[0]
        tag = data[offset+4:offset+8]
        chunk = data[offset+8:offset+8+n]
        offset += 12+n
        if tag == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", chunk[:10])
        if tag == b"IDAT":
            pixels.extend(chunk)
        if tag == b"IEND":
            break
    if depth != 8 or colour not in (2, 6):
        raise ValueError(f"Unsupported PNG format: depth={depth} colour={colour}")
    channels = 3 if colour == 2 else 4
    line = 1 + width * channels
    raw = zlib.decompress(pixels)
    if len(raw) != line * height:
        raise ValueError("Unexpected PNG scanline structure")
    decoded = bytearray()
    prev = bytearray(width * channels)
    bpp = channels
    for y in range(height):
        block = raw[y*line:(y+1)*line]
        f = block[0]
        cur = bytearray(block[1:])
        for i in range(len(cur)):
            a = cur[i-bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i-bpp] if i >= bpp else 0
            if f == 1: cur[i] = (cur[i] + a) & 255
            elif f == 2: cur[i] = (cur[i] + b) & 255
            elif f == 3: cur[i] = (cur[i] + ((a+b)//2)) & 255
            elif f == 4:
                p = a+b-c
                pa,pb,pc = abs(p-a),abs(p-b),abs(p-c)
                cur[i] = (cur[i] + (a if pa<=pb and pa<=pc else b if pb<=pc else c)) & 255
            elif f != 0:
                raise ValueError(f"Unsupported PNG filter {f}")
        if y >= 80:
            decoded.extend(cur)
        prev = cur
    return hashlib.sha256(decoded).hexdigest()


def main(folder):
    p = Path(folder)
    before = describe(p/"chatgpt-first-run.xml")
    after = describe(p/"real-chatgpt-end.xml")
    first_png = png_body_hash(p/"chatgpt-after-official-skip.png")
    ready_png = png_body_hash(p/"real-chatgpt-ready.png")
    result = {
        "before": before,
        "after": after,
        "click_report": (p/"guest-onboarding-result.txt").read_text().strip(),
        "first_png_body_sha256": first_png,
        "ready_png_body_sha256": ready_png,
        "onboarding_still_visible_after_attempt": after["welcome_visible"] and after["skip_visible"],
        "body_identical_after_click": first_png == ready_png,
        "message_composer_not_available": not after["composer_visible"],
    }
    result["diagnosis"] = (
        "ONBOARDING_NOT_DISMISSED_BEFORE_RELAY_JOB"
        if result["onboarding_still_visible_after_attempt"] and
           result["body_identical_after_click"] and result["message_composer_not_available"]
        else "NOT_PROVEN_BY_THIS_EVIDENCE"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    assert result["diagnosis"] == "ONBOARDING_NOT_DISMISSED_BEFORE_RELAY_JOB", result["diagnosis"]


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv)>1 else "real-chatgpt-evidence")
