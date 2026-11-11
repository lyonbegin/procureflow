"""Regression: a second Android connection must not tear down the first."""
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["RELAY_DATA_DIR"] = tempfile.mkdtemp(prefix="relay-owner-test-")
os.environ["DEVICE_TOKEN"] = "ci-owner-test-token-not-production"
os.environ["CONSOLE_TOKEN"] = "ci-console-test-token-not-production"
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app import app

packet = {"role": "device", "deviceId": "android-main",
          "token": os.environ["DEVICE_TOKEN"]}
with TestClient(app) as client:
    with client.websocket_connect("/ws") as owner:
        owner.send_json(packet)
        first = owner.receive_json()
        assert first["type"] == "auth.ok", first
        assert client.get("/health").json()["deviceOnline"] is True
        with client.websocket_connect("/ws") as contender:
            contender.send_json(packet)
            refused = contender.receive_json()
            assert refused["type"] == "auth.error", refused
            assert "already connected" in refused["reason"], refused
            try:
                contender.receive_json()
                raise AssertionError("Contender socket remained connected")
            except WebSocketDisconnect:
                pass
        assert client.get("/health").json()["deviceOnline"] is True
        owner.send_json({"type": "ping"})
        pong = owner.receive_json()
        assert pong["type"] == "pong", pong
        print("PASS_DUPLICATE_ANDROID_REJECTED_ORIGINAL_SESSION_REMAINS_ONLINE", flush=True)
