#!/usr/bin/env python3
"""Offline pinned-vendor regression assertions; zero ChatGPT/Relay requests."""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root/"src"))
from chatgpt_web2api.chatgpt_dom import ChatGPTDom

class FakeDriver:
    def __init__(self, actual):
        self.actual = actual
        self._js_strict = AsyncMock(side_effect=lambda *a, **k: json.dumps(self.actual))
    
def case(actual, intended):
    return asyncio.run(ChatGPTDom(FakeDriver(actual))._verify_composer_text(
        'div[role="textbox"].ProseMirror', intended))

text="교재 1학년 수학\n합성 제목 001~020"
assert case({"parts":text,"visible":text,"raw":text.replace("\n","")}, text) is True
assert case({"parts":text.replace("\n",""),"visible":text,"raw":text.replace("\n","")}, text) is True
assert case({"parts":text.replace("\n",""),"visible":text.replace("\n",""),"raw":text.replace("\n","")}, text) is False
assert case({"parts":"이전 질문","visible":"이전 질문","raw":"이전 질문"}, text) is False
assert case({"parts":"이전 질문"+text,"visible":"이전 질문"+text,"raw":"이전 질문"+text}, text) is False
assert case({"parts":text+"\n","visible":text+"\n","raw":text}, text) is True
assert case({"parts":"가나다","visible":"가나다","raw":"가나다"}, "가나다") is True
assert case({"parts":"한글\u00a0문자","visible":"한글\u00a0문자","raw":"한글\u00a0문자"}, "한글 문자") is True
assert case({"parts":"","visible":"","raw":""}, text) is False
assert case({"parts":"변조","visible":"변조","raw":"변조"}, "원본") is False
dom = (root/"src/chatgpt_web2api/chatgpt_dom.py").read_text("utf-8")
api = (root/"src/chatgpt_web2api/api_server.py").read_text("utf-8")
assert 'full_text = conversation_lines[0][len("[User]\\n"):]' in api
assert "Array.from(document.querySelectorAll(" in dom
assert "Composer text verification failed after retry; expected" not in dom
assert 'logger.info("Typed: %s", text[:80])' not in dom
print("PASS_OFFLINE_PINNED_VENDOR_EXACT_MULTILINE_10_CASES")
print("PASS_OFFLINE_PINNED_VENDOR_NO_RAW_PROMPT_IN_FAILURE")
