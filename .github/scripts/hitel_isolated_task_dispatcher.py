#!/usr/bin/env python3
"""GitHub-only task runner scheduler: no Railway GitHub secret is necessary.

Poll only the existing Railway service for *counts*, then dispatch one
independent GitHub Actions worker per task_id with a stable OIDC-bound
workflow. Never start duplicate workers for a queued/in-progress task.
Never send, retry, or cancel any ChatGPT request.
"""
import json
import os
import urllib.error
import urllib.request

ROOT="https://hitel-integration-api-production.up.railway.app"
API="https://api.github.com"
WORKFLOW="hitel-isolated-chrome-worker.yml"
TASKS={"stock-a","stock-tv","scribd-18109"}
ACTIVE={"queued","in_progress","waiting","pending","requested"}


def read_json(url,token=None):
    headers={"Accept":"application/vnd.github+json"}
    if token:
        headers["Authorization"]="Bearer "+token
        headers["X-GitHub-Api-Version"]="2022-11-28"
    req=urllib.request.Request(url,headers=headers)
    with urllib.request.urlopen(req,timeout=20) as res:
        return json.load(res)


def dispatch(token,repo,task_id):
    req=urllib.request.Request(
        API+"/repos/"+repo+"/actions/workflows/"+WORKFLOW+"/dispatches",
        data=json.dumps({"ref":"main","inputs":{"task_id":task_id}}).encode(),
        method="POST",headers={
            "Accept":"application/vnd.github+json",
            "X-GitHub-Api-Version":"2022-11-28",
            "Authorization":"Bearer "+token,
            "Content-Type":"application/json",
        })
    try:
        with urllib.request.urlopen(req,timeout=24) as res:
            status=res.status
    except urllib.error.HTTPError as exc:
        status=exc.code
    if status in (200,201,204):
        return "worker_start_accepted"
    if status in (500,502,503,504):
        # The 5xx may mean accepted-but-not-yet-indexed. Never repost in
        # the same run. Future schedulers re-check GitHub's full run list.
        return "dispatch_ambiguous_recheck_next_schedule"
    raise RuntimeError("TASK_DISPATCH_HTTP_"+str(status))


def plan(tasks,runs):
    result={}
    for task in tasks:
        tid=task.get("task_id")
        if tid not in TASKS:
            raise ValueError("UNKNOWN_TASK_ID_FAIL_CLOSED")
        connected=task.get("worker_connected") is True
        queued=task.get("queued_jobs_count")
        active_jobs=task.get("worker_active_jobs_count")
        if not isinstance(queued,int) or isinstance(queued,bool) or queued<0:
            raise ValueError("INVALID_TASK_QUEUE_COUNT")
        if not isinstance(active_jobs,int) or isinstance(active_jobs,bool) or active_jobs<0:
            raise ValueError("INVALID_TASK_ACTIVE_JOB_COUNT")
        already=any(r.get("head_branch")=="main" and
                    r.get("path")==".github/workflows/"+WORKFLOW and
                    r.get("display_title")=="HITEL isolated Chrome "+tid and
                    r.get("status") in ACTIVE for r in runs)
        if connected:
            result[tid]="healthy"
        elif already:
            result[tid]="worker_queued_or_running"
        elif queued<=0:
            result[tid]="no_queued_job"
        else:
            result[tid]="dispatch"
    return result


def main():
    import urllib.error
    token=os.environ["GH_TOKEN"]
    repo=os.environ["GITHUB_REPOSITORY"]
    try:
        public=read_json(ROOT+"/integrations/v1/public/isolated/tasks/pending")
    except urllib.error.HTTPError as exc:
        if exc.code in (404,502,503,504):
            # The Railway service may still be rolling out the additive API.
            # This is not permission to launch a worker against an old relay.
            print("WAIT_ISOLATED_TASK_API_ROLLOUT_HTTP",exc.code,flush=True)
            return 0
        raise
    except (urllib.error.URLError,TimeoutError,OSError) as exc:
        print("WAIT_ISOLATED_TASK_API_NETWORK",type(exc).__name__,flush=True)
        return 0
    tasks=public.get("tasks",[])
    if len(tasks)!=len(TASKS) or set(x.get("task_id") for x in tasks)!=TASKS:
        raise ValueError("TASK_REGISTRY_MISMATCH_NO_DISPATCH")
    runs=read_json(API+"/repos/"+repo+"/actions/workflows/"+WORKFLOW+
                   "/runs?per_page=100",token=token).get("workflow_runs",[])
    decisions=plan(tasks,runs)
    for tid in sorted(decisions):
        state=decisions[tid]
        if state=="dispatch":
            state=dispatch(token,repo,tid)
        print("HITEL_ISOLATED_TASK_DISPATCH",tid,state,flush=True)


if __name__=="__main__":
    raise SystemExit(main())
