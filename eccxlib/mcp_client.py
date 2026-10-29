"""Minimal MCP client over stdio (newline-delimited JSON-RPC 2.0).

Claude Code ships an MCP client; a bare agent does not. This is enough of one to
be useful: initialize, tools/list, tools/call, with per-call process lifetime
(no long-lived daemon to leak). Only servers that can actually start here are
reachable — most entries in mcp-configs/mcp-servers.json want npx/uvx network
access and an API key, so `eccx tools` marks them unbootable instead of hanging.
"""
from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .util import ADAPTER_STATE, ECC_ROOT, load_json

PROTOCOL = "2025-06-18"
CLIENT_INFO = {"name": "eccx", "version": "1.0.0"}


class MCPError(RuntimeError):
    pass


class StdioClient:
    def __init__(self, command: str, args: list[str] | None = None,
                 env: dict | None = None, cwd: str | None = None,
                 timeout: float = 20.0):
        self.command = command
        self.args = args or []
        self.extra_env = env or {}
        self.cwd = cwd
        self.timeout = timeout
        self.proc: subprocess.Popen | None = None
        self._next_id = 0

    def __enter__(self):
        import os
        env = dict(os.environ)
        env.update({k: str(v) for k, v in self.extra_env.items()})
        self.proc = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=env, cwd=self.cwd,
        )
        # Read on a thread. `self.timeout` used to be checked between lines, so a
        # server that simply never answers blocked `readline()` forever: the
        # timeout was a comment, not a guarantee. A queue makes it real.
        self._lines: queue.Queue = queue.Queue()
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        return self

    def _pump(self) -> None:
        assert self.proc and self.proc.stdout
        try:
            for line in self.proc.stdout:
                self._lines.put(line)
        except Exception:
            pass
        self._lines.put(None)  # EOF sentinel

    def __exit__(self, *exc):
        if not self.proc:
            return
        if self.proc.poll() is None:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3)
            except Exception:
                self.proc.kill()
                try:
                    self.proc.wait(timeout=2)
                except Exception:
                    pass
        for stream in (self.proc.stdout, self.proc.stderr, self.proc.stdin):
            try:
                if stream and not stream.closed:
                    stream.close()
            except Exception:
                pass
        if hasattr(self.proc, "stdin") and self.proc.stdin and not self.proc.stdin.closed:
            try:
                self.proc.stdin.close()
            except Exception:
                pass

    def _send(self, obj: dict) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _read(self) -> dict:
        assert self.proc
        deadline = time.time() + self.timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise MCPError(f"timeout after {self.timeout}s waiting for a "
                               f"JSON-RPC response")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                raise MCPError(f"timeout after {self.timeout}s waiting for a "
                               f"JSON-RPC response")
            if line is None:
                err = ""
                try:
                    err = (self.proc.stderr.read() or "")[-500:]
                except Exception:
                    pass
                raise MCPError(f"server closed the stream. stderr: {err.strip()}")
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    def request(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        rid = self._next_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method,
                    "params": params or {}})
        while True:
            msg = self._read()
            if msg.get("id") != rid:
                continue  # notification or unrelated response
            if "error" in msg:
                raise MCPError(f"{method}: {msg['error'].get('message', msg['error'])}")
            return msg.get("result", {})

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self) -> dict:
        res = self.request("initialize", {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "clientInfo": CLIENT_INFO,
        })
        self.notify("notifications/initialized")
        return res

    def list_tools(self) -> list[dict]:
        return self.request("tools/list", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments})


LOCAL_OVERRIDES = ADAPTER_STATE / "mcp-local.json"

# Servers that ECC ships but whose launcher is a Claude-Code-only npm bin. These
# overrides point them at the real entry file so the sandbox can boot them.
BUILTIN_OVERRIDES = {
    "ecc-memory-vault": {
        "command": "node",
        "args": [str(ECC_ROOT / "scripts" / "memory-mcp.mjs")],
        "env": {"ECC_MEMORY_HARNESS": "eccx"},
        "description": "ECC Memory Vault (shared store, driven over stdio MCP)",
    },
}


PROBE_CACHE = ADAPTER_STATE / "mcp-probe.json"


def probe_all(servers: dict, parallel: bool = True, ttl: int = 3600,
              refresh: bool = False, timeout: float = 10.0) -> list[dict]:
    """Probe every configured server, bounded and cached.

    Sequential npx probes cost ~2.5 minutes; that is unacceptable in a loop, so
    results are cached for `ttl` seconds and probes run concurrently. Servers
    whose launcher is missing are resolved without spawning anything.
    """
    import json as _json
    from concurrent.futures import ThreadPoolExecutor

    cache = load_json(PROBE_CACHE, {}) or {}
    now = time.time()
    todo, out = [], []
    for name, srv in servers.items():
        cached = cache.get(name)
        if (not refresh and cached and now - cached.get("ts", 0) < ttl):
            rec = dict(cached["rec"])
            rec["cached"] = True
            out.append(rec)
        else:
            todo.append((name, srv))

    def work(item):
        name, srv = item
        return probe(name, srv, timeout=timeout)

    if todo:
        if parallel and len(todo) > 1:
            with ThreadPoolExecutor(max_workers=min(8, len(todo))) as ex:
                results = list(ex.map(work, todo))
        else:
            results = [work(i) for i in todo]
        for rec in results:
            cache[rec["name"]] = {"ts": now, "rec": rec}
            out.append(rec)
        try:
            PROBE_CACHE.parent.mkdir(parents=True, exist_ok=True)
            PROBE_CACHE.write_text(_json.dumps(cache, indent=1), encoding="utf-8")
        except Exception:
            pass

    order = list(servers)
    out.sort(key=lambda r: (not r.get("ok"), order.index(r["name"])
                            if r["name"] in order else 99))
    return out


def configured_servers() -> dict:
    cfg = load_json(ECC_ROOT / "mcp-configs" / "mcp-servers.json", {}) or {}
    servers = dict(cfg.get("mcpServers", {}))
    servers.update({k: dict(v) for k, v in BUILTIN_OVERRIDES.items()})
    servers.update(load_json(LOCAL_OVERRIDES, {}) or {})
    return servers


def bootable(command: str) -> bool:
    if "/" in command:
        return Path(command).exists()
    return shutil.which(command) is not None


def probe(name: str, server: dict, timeout: float = 12.0) -> dict:
    """Try a real handshake and tool listing. Returns a status record."""
    cmd = server.get("command", "")
    rec = {"name": name, "command": cmd, "args": server.get("args", []),
           "description": (server.get("description") or "")[:160]}
    if not bootable(cmd):
        rec.update(ok=False, status="unavailable", detail=f"'{cmd}' not on PATH")
        return rec
    try:
        with StdioClient(cmd, server.get("args", []), server.get("env"),
                         timeout=timeout) as c:
            info = c.initialize()
            tools = c.list_tools()
        rec.update(ok=True, status="ready", detail="handshake ok",
                   server_info=info.get("serverInfo", {}),
                   tools=[t.get("name") for t in tools])
    except Exception as exc:
        rec.update(ok=False, status="failed", detail=str(exc)[:300])
    return rec
