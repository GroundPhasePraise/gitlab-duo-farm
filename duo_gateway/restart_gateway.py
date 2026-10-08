"""Restart the GitLab Duo gateway (server.py) on :8088 as a detached process.

Usage: python restart_gateway.py
"""
if __name__ != "__main__" and not __import__("os").environ.get("GLAR_ALLOW_IMPORT"):
    raise ImportError(f"{__name__}: script-only module — run it directly (python {__file__})")

import os, subprocess, sys, time, json

VENV_PY = sys.executable
CWD = r"C:\Users\User\Desktop\gitlab-autoreg\duo_gateway"

def parse_pid():
    import re
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if ":8088" in line and "LISTENING" in line:
            return int(line.split()[-1])
    return None

pid = parse_pid()
if pid:
    print("stopping old gateway pid", pid, flush=True)
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    time.sleep(2)

# detached launch (survives parent death): CREATE_NEW_PROCESS_GROUP + DETACHED
DETACHED = 0x8 | 0x200
flags = subprocess.CREATE_NEW_PROCESS_GROUP | DETACHED
proc = subprocess.Popen(
    [VENV_PY, "-u", "server.py"], cwd=CWD, stdout=open("gw_stdout.log", "a"),
    stderr=open("gw_stderr.log", "a"), creationflags=flags, close_fds=True)
print("gateway launched pid", proc.pid, flush=True)
time.sleep(6)
import urllib.request
try:
    r = urllib.request.urlopen("http://127.0.0.1:8088/health", timeout=8)
    print("health:", r.status, r.read()[:120], flush=True)
except Exception as e:
    print("health ERR:", e, flush=True)