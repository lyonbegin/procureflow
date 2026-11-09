import os
import uuid
from pathlib import Path

os.environ.setdefault("CONSOLE_TOKEN", "test-console-token")
os.environ.setdefault("DEVICE_TOKEN", "test-device-token")
from fastapi.testclient import TestClient
from app import app

def main():
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        with client.websocket_connect("/ws") as device:
            device.send_json({"type": "auth", "role": "device", "deviceId": "android-main", "token": "test-device-token"})
            assert device.receive_json()["type"] == "auth.ok"
            with client.websocket_connect("/ws") as console:
                console.send_json({"type": "auth", "role": "console", "token": "test-console-token"})
                auth = console.receive_json()
                assert auth["type"] == "auth.ok" and auth["deviceOnline"]
                assert console.receive_json()["type"] == "device.status"  # replay
                identifier = uuid.uuid4().hex
                console.send_json({"type": "command", "id": identifier, "action": "chat.send", "payload": {"text": "Integration test"}})
                accepted = console.receive_json()
                assert accepted["type"] == "command.accepted" and accepted["id"] == identifier
                forwarded = device.receive_json()
                assert forwarded["type"] == "command" and forwarded["action"] == "chat.send"
                assert forwarded["payload"]["text"] == "Integration test"
                assert console.receive_json()["type"] == "command.queued"
                device.send_json({"type": "command.received", "id": identifier, "stage": "Android socket received"})
                assert console.receive_json()["type"] == "command.received"
                device.send_json({"type": "command.progress", "id": identifier, "stage": "text inserted"})
                status = console.receive_json()
                assert status["type"] == "command.progress" and status["stage"] == "text inserted"
                device.send_json({"type": "command.result", "id": identifier, "result": {"stage": "send_confirmed_composer_cleared_via_named"}})
                result = console.receive_json()
                assert result["type"] == "command.result" and result["id"] == identifier
                assert result["result"]["stage"].startswith("send_confirmed")
                print("PASS: web -> Railway -> Android -> progress -> result", flush=True)

if __name__ == "__main__":
    main()
