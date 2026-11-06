#!/usr/bin/env python3
"""Single Railway service: shared Studio, production API and optional G2B collectors.

No official n8n daemon, queue worker or Redis is installed. The API and worker
are started only with explicit configuration to avoid duplicate live jobs.
"""
import os
import signal
import subprocess
import sys
import time

PROCESSES = {}
stopping = False

def launch(name, args, extra=None):
    env = os.environ.copy()
    env.update(extra or {})
    process = subprocess.Popen(args, env=env, cwd="/app", start_new_session=True)
    PROCESSES[name] = process
    print(f"UNIFIED_START {name} pid={process.pid}", flush=True)

def stop(signum=None, _frame=None):
    global stopping
    stopping = True
    for name, proc in reversed(list(PROCESSES.items())):
        if proc.poll() is None:
            try: os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError: pass
    deadline = time.monotonic() + 15
    for proc in PROCESSES.values():
        try: proc.wait(timeout=max(0.1, deadline-time.monotonic()))
        except subprocess.TimeoutExpired:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass

def main():
    if os.environ.get("PORT", "3000") != "3000":
        raise SystemExit("UNIFIED_EXPECTS_RAILWAY_PORT_3000")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    launch("studio", ["gosu", "studio", "python3", "-u", "/app/studio_server.py"],
           {"PORT": "3001"})
    database = bool(os.environ.get("DATABASE_URL"))
    fresh_db = bool(os.environ.get("FRESH_DATABASE_URL"))
    if database:
        launch("api", ["gosu", "studio", "uvicorn", "main:app",
                       "--host", "127.0.0.1", "--port", "8001"])
        launch("history", ["gosu", "studio", "uvicorn", "focused_g2b:app",
                           "--host", "127.0.0.1", "--port", "8003"])
    else:
        print("UNIFIED_API_HOLD_DATABASE_URL_NOT_CONFIGURED", flush=True)
    if fresh_db:
        launch("fresh", ["gosu", "studio", "uvicorn", "fresh_g2b_app:app",
                         "--host", "127.0.0.1", "--port", "8002"])
    else:
        print("UNIFIED_FRESH_HOLD_ISOLATED_DATABASE_URL_NOT_CONFIGURED", flush=True)
    if os.environ.get("PROCUREFLOW_EMBEDDED_WORKER_ENABLED", "0") == "1":
        if not database:
            raise SystemExit("WORKER_START_BLOCKED_DATABASE_URL_MISSING")
        if os.environ.get("PROCUREFLOW_ORIGINAL_WORKER_STOPPED") != "1":
            raise SystemExit("WORKER_START_BLOCKED_ORIGINAL_WORKER_NOT_CONFIRMED_STOPPED")
        launch("worker", ["gosu", "studio", "python3", "-u", "worker.py"])
    else:
        print("UNIFIED_COLLECTOR_HOLD_DUPLICATE_WORKER_PREVENTED", flush=True)
    launch("proxy", ["nginx", "-g", "daemon off;"])
    try:
        while not stopping:
            for name, proc in list(PROCESSES.items()):
                rc = proc.poll()
                if rc is not None:
                    print(f"UNIFIED_PROCESS_EXIT name={name} code={rc}", flush=True)
                    return 1
            time.sleep(1)
        return 0
    finally: stop()

if __name__ == "__main__":
    sys.exit(main())