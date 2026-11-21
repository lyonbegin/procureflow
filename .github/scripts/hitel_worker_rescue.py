#!/usr/bin/env python3
"""Independent, five-minute Chrome worker resurrection guard.

The classifier's 5-minute watchdog cannot launch the worker in this repo:
its GITHUB_TOKEN is repository scoped. This guard runs with procureau
permissions and starts the EXISTING Chrome worker workflow, with the
registered encrypted profile, exactly as before.

It never submits or retries any ChatGPT request. It fences existing jobs
by consulting the Railway status. An interrupted remote job must be
resolved by the classifier, not by the worker rescue scheduler.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.request

WORKFLOW = "hitel-integration-bridge-live-qa.yml"
WORKER_NAME = "HITEL - Start Chrome API worker (manual) / Verify owner pairing"
SERVICE = "https://hitel-integration-api-production.up.railway.app/integrations/v1/public/status"
API = "https://api.github.com"
ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested"}
RECOVERY_MIN_AGE_SECONDS = 480
TITLE_PREFIX = "HITEL Chrome worker "
DISPATCH_CHECKS = 6


def age_seconds(iso: str) -> float:
    return (dt.datetime.now(dt.timezone.utc)
            - dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds()


class Github:
    def __init__(self, token, repository):
        if not token or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("MISSING_AUTH_OR_INVALID_REPOSITORY")
        self.token, self.repository = token, repository

    def request(self, verb, path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            API + "/repos/" + self.repository + "/" + path,
            method=verb, data=body, headers={
                "Accept": "application/vnd.github+json",
                "Authorization": "Bearer " + self.token,
                "X-GitHub-Api-Version": "2022-11-28",
                **({"Content-Type": "application/json"} if body else {}),
            })
        try:
            with urllib.request.urlopen(req, timeout=24) as res:
                raw = res.read()
                return res.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            # API error payloads may include private data; never print them.
            return exc.code, None


def railway_status():
    with urllib.request.urlopen(SERVICE, timeout=12) as res:
        obj = json.load(res)
    if not isinstance(obj.get("worker_active_jobs_count"), int):
        raise RuntimeError("UNKNOWN_RAILWAY_ACTIVE_JOBS_REFUSE_WORKER_CANCEL")
    return obj


def list_worker_runs(api):
    status, data = api.request("GET",
                               "actions/workflows/"+WORKFLOW+"/runs?per_page=100")
    if status != 200 or not isinstance(data, dict):
        raise RuntimeError("WORKER_RUNS_DISCOVERY_HTTP_"+str(status))
    runs = [r for r in data.get("workflow_runs", [])
            if r.get("head_branch") == "main"
            and r.get("name") == WORKER_NAME]
    return sorted(runs, key=lambda r: r["created_at"], reverse=True)


def find_token(runs, token):
    return next((int(r["id"]) for r in runs
                 if r.get("display_title") == TITLE_PREFIX+token), None)


def launch_existing_worker(api, token, sleep=time.sleep):
    if not re.fullmatch(r"rescue-(?:after|replace)-[0-9]+", token):
        raise ValueError("BAD_RESCUE_TOKEN")
    payload = {"ref": "main", "inputs": {
        "operation": "worker_only", "run_minutes": "240",
        "rescue_token": token}}
    for attempt in range(1, 3):
        runs = list_worker_runs(api)
        seen = find_token(runs, token)
        if seen:
            print("WORKER_RESCUE_ALREADY_DISPATCHED", seen, flush=True)
            return ("already_dispatched", seen)
        # An indexed queued or running worker is always preferable to a new
        # request, even if this watchdog has a different token.
        if any(r["status"] in ACTIVE for r in runs):
            return ("worker_already_queued_or_running", None)
        code, _ = api.request(
            "POST", "actions/workflows/"+WORKFLOW+"/dispatches", payload)
        print("WORKER_RESCUE_DISPATCH_HTTP", code, "ATTEMPT", attempt, flush=True)
        if code == 204:
            # 204 means accepted. Never POST again even if indexing lags.
            return ("accepted", None)
        if code not in (500, 502, 503, 504):
            raise RuntimeError("WORKER_RESCUE_NONRETRYABLE_HTTP_"+str(code))
        for i in range(DISPATCH_CHECKS):
            sleep(4)
            runs = list_worker_runs(api)
            seen = find_token(runs, token)
            if seen:
                return ("accepted_after_5xx", seen)
            if any(r["status"] in ACTIVE for r in runs):
                return ("worker_visible_after_5xx", None)
        # Don't immediately repeat an ambiguous 500; leave at least 5 minutes
        # to the next scheduled check before another possible dispatch.
        return ("ambiguous_5xx_recheck_next_schedule", None)
    return ("no_post", None)


def monitor(api, status, runs, probe=lambda: railway_status(),
            sleep=time.sleep):
    connected = (status.get("worker_connected") is True
                 and status.get("worker_heartbeat_recent") is True
                 and status.get("worker_bootstrap_ready") is True)
    active_count = status.get("worker_active_jobs_count")
    if not isinstance(active_count, int) or isinstance(active_count, bool):
        raise RuntimeError("UNKNOWN_ACTIVE_JOBS_FAIL_CLOSED")
    current = [r for r in runs if r.get("status") in ACTIVE]
    print("WORKER_RESCUE_5MIN_CHECK",
          "CONNECTED", connected, "ACTIVE_JOBS", active_count,
          "ACTIVE_WORKER_RUNS", [r["id"] for r in current], flush=True)
    if connected:
        return "healthy"
    if active_count != 0:
        # Never kill a worker with queued or in-flight ChatGPT requests.
        return "inflight_preserved"
    if current:
        # A pending worker is already a recovery action; don't create another.
        if any(r["status"] != "in_progress" for r in current):
            return "startup_or_queued"
        runner = current[0]
        if age_seconds(runner["created_at"]) < RECOVERY_MIN_AGE_SECONDS:
            return "startup_grace"
        sleep(5)
        second = probe()
        if (second.get("worker_connected") is True
                or second.get("worker_heartbeat_recent") is True
                or second.get("worker_active_jobs_count") != 0):
            return "reconnected_or_inflight_preserved"
        # The exact runner has not established a heartbeat after >8 minutes,
        # there are no active ChatGPT requests, and two checks agree.
        response, _ = api.request("POST",
            "actions/runs/"+str(runner["id"])+"/cancel")
        if response not in (202, 409):
            raise RuntimeError("UNHEALTHY_WORKER_CANCEL_HTTP_"+str(response))
        print("UNHEALTHY_EMPTY_WORKER_CANCEL_REQUESTED",
              runner["id"], "HTTP", response, flush=True)
        # The existing same concurrency group permits the replacement to
        # queue while old cancellation finishes, but never cancels the new one.
        # Do not assume the canceled run is already absent from GitHub's list.
        token = "rescue-replace-"+str(runner["id"])
        # Launch without the in-progress check: cancellation is intentional,
        # explicit, and guarded by empty/inactive railway remote status.
        p = {"ref": "main", "inputs": {
            "operation": "worker_only", "run_minutes": "240",
            "rescue_token": token}}
        code, _ = api.request(
            "POST", "actions/workflows/"+WORKFLOW+"/dispatches", p)
        if code == 204:
            print("WORKER_RESCUE_REPLACEMENT_ACCEPTED",token,flush=True)
            return "replacement_queued"
        if code in (500,502,503,504):
            # Next cron checks the queued run or resumes if cancellation won.
            return "ambiguous_replacement_dispatch_recheck"
        raise RuntimeError("REPLACEMENT_DISPATCH_HTTP_"+str(code))

    previous = runs[0]["id"] if runs else 0
    token = "rescue-after-"+str(previous)
    result, _ = launch_existing_worker(api, token, sleep=sleep)
    return result


def main():
    api = Github(os.environ["GH_TOKEN"],os.environ["GITHUB_REPOSITORY"])
    status = railway_status()
    runs = list_worker_runs(api)
    result = monitor(api,status,runs)
    print("WORKER_RESCUE_RESULT",result,flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as f:
            f.write("Chrome worker five-minute rescue: "+result+"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
