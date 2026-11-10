#!/usr/bin/env python3
"""Host-side API driver for an actual Android controller on a CI emulator.

The websocket endpoint is the ephemeral FastAPI test server on the runner.
Successful file transfer is not presented as successful ChatGPT app attachment.
"""
import base64
import hashlib
import json
import os
import sys
import time
import httpx

BASE = "http://127.0.0.1:8765"
ADMIN = {"X-Console-Token": os.environ["CONSOLE_TOKEN"]}
USER = "android_ci_live"


def post(path, **kwargs):
    with httpx.Client(timeout=20) as client:
        response = client.post(BASE + path, headers=ADMIN, **kwargs)
    response.raise_for_status()
    return response.json()


def get(path):
    with httpx.Client(timeout=20) as client:
        response = client.get(BASE + path, headers=ADMIN)
    response.raise_for_status()
    return response.json()


def main():
    action = sys.argv[1]
    if action == "init":
        post("/api/v1/users", json={"user_id": USER, "name": "Ephemeral Android CI"})
        room = post("/api/v1/rooms", json={
            "user_id": USER, "title": "Actual Android WebSocket negative test"
        })
        print(room["id"])
    elif action == "text":
        room_id = sys.argv[2]
        job = post("/api/v1/rooms/" + room_id + "/messages",
                   json={"user_id": USER, "text":
                         "Confirm no chat message is sent without the official ChatGPT app"})
        print(job["id"])
    elif action == "files":
        room_id = sys.argv[2]
        # Actual image bytes and a document payload, not a text URL.
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg=="
        )
        document = b"Android WebSocket integration test\n" + bytes(range(256)) * 16
        with httpx.Client(timeout=20) as client:
            response = client.post(
                BASE + "/api/v1/rooms/" + room_id + "/turns",
                headers=ADMIN,
                data={"user_id": USER, "text": "Inspect the real image and document bytes"},
                files=[
                    ("files", ("tiny.png", png, "image/png")),
                    ("files", ("document.txt", document, "text/plain")),
                ],
            )
        response.raise_for_status()
        data = response.json()
        files = data["files"]
        assert [f["sha256"] for f in files] == [
            hashlib.sha256(png).hexdigest(), hashlib.sha256(document).hexdigest()
        ]
        print(json.dumps({"job_id": data["id"], "files": [
            {"id": f["id"], "name": f["name"], "sha256": f["sha256"]}
            for f in files
        ]}))
    elif action == "assert-failed":
        jid = sys.argv[2]
        for _ in range(90):
            job = get("/api/v1/jobs/" + jid + "?user_id=" + USER)
            if job["status"] in ("failed", "completed"):
                break
            time.sleep(.5)
        else:
            raise AssertionError("Real Android controller did not finish job")
        assert job["status"] == "failed", job
        assert "Official ChatGPT is not installed" in (job.get("error") or ""), job
        assert job.get("result_text") is None, job
        print(json.dumps({
            "job_id": jid, "status": job["status"], "stage": job["stage"],
            "reason": job["error"]
        }, ensure_ascii=False))
    elif action == "online":
        with httpx.Client(timeout=5) as client:
            health = client.get(BASE + "/health").json()
        assert health["deviceOnline"] is True, health
        print("PASS_AUTHENTICATED_ACTUAL_ANDROID_WEBSOCKET_CONNECTION")
    else:
        raise SystemExit("Unknown test action: " + action)


if __name__ == "__main__":
    main()
