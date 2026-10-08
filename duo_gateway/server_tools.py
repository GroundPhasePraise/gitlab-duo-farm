"""Server-side tool executor for the GitLab Duo gateway.

When config.server_tools is on, the gateway itself runs whitelisted tools on
the host PC (bash/read/write/list/calc), feeds results back to the model and
returns the final answer — one API roundtrip gives real PC access.

Security: the API key is the only gate. Keep GATEWAY_SERVER_TOOLS off unless
the gateway is only reachable by trusted callers (127.0.0.1 by default).
"""
import ast
import json
import operator
import os
import subprocess
from pathlib import Path

MAX_OUT = 6000        # chars per tool result
MAX_FILE = 200_000    # bytes read/write cap
CMD_TIMEOUT = 60

ALLOWED = {"bash", "run_command", "shell", "cmd", "read", "read_file",
           "write", "write_file", "list", "list_dir", "ls", "calc", "python",
           "screenshot", "screen"}

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod, ast.Pow: operator.pow,
        ast.USub: operator.neg, ast.UAdd: operator.pos}


def _calc(expr: str):
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp):
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp):
            return _OPS[type(node.op)](ev(node.operand))
        raise ValueError("unsupported expression")
    return ev(ast.parse(expr, mode="eval"))


def _clip(s: str) -> str:
    s = s.strip()
    return s if len(s) <= MAX_OUT else s[:MAX_OUT] + f"\n…[truncated {len(s) - MAX_OUT} chars]"


def _bash(cmd: str) -> str:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                       timeout=CMD_TIMEOUT)
    out = (r.stdout or "") + (("\n[stderr] " + r.stderr) if r.stderr else "")
    return _clip(f"exit={r.returncode}\n{out}")


def _python(code: str) -> str:
    r = subprocess.run(["python", "-c", code], capture_output=True, text=True,
                       timeout=CMD_TIMEOUT)
    out = (r.stdout or "") + (("\n[stderr] " + r.stderr) if r.stderr else "")
    return _clip(f"exit={r.returncode}\n{out}")


def _read(path: str) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"not found: {path}"
    if p.is_dir():
        return _clip("\n".join(sorted(os.listdir(p))))
    data = p.read_bytes()[:MAX_FILE]
    try:
        return _clip(data.decode("utf-8", errors="replace"))
    except Exception as e:
        return f"read error: {e}"


def _write(path: str, content: str) -> str:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content[:MAX_FILE], encoding="utf-8")
    return f"written: {p} ({len(content[:MAX_FILE])} bytes)"


def _list(path: str) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"not found: {path}"
    items = sorted(os.listdir(p))[:300]
    return f"{p} ({len(items)} items)\n" + "\n".join(items)


def execute(name: str, arguments) -> str:
    """Run one whitelisted tool; return the result text."""
    args = dict(arguments or {})
    n = (name or "").strip().lower()
    if n in ("bash", "run_command", "shell", "cmd"):
        return _bash(str(args.get("command") or args.get("cmd") or ""))
    if n == "python":
        return _python(str(args.get("code") or ""))
    if n in ("read", "read_file"):
        return _read(str(args.get("path", "")))
    if n in ("write", "write_file"):
        return _write(str(args.get("path", "")), str(args.get("content", "")))
    if n in ("list", "list_dir", "ls"):
        return _list(str(args.get("path") or args.get("dir") or "."))
    if n == "calc":
        try:
            return str(_calc(str(args.get("expr") or args.get("expression") or "")))
        except Exception as e:
            return f"calc error: {e}"
    if n in ("screenshot", "screen"):
        try:
            import vision_bridge
            return vision_bridge.screenshot_describe(str(args.get("question") or ""))
        except Exception as e:
            return f"screenshot error: {e}"
    raise ValueError(f"tool not whitelisted for server-side exec: {name}")


def can_execute(name: str) -> bool:
    return (name or "").strip().lower() in ALLOWED