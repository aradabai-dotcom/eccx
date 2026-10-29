"""Durable memory — the layer that survives context compaction.

ECC ships a memory vault (`ecc memory ...`) backed by the project's .ecc
folder plus a SQLite state DB. Rather than re-implement it, eccx drives the
official Node CLI so both harnesses share the same store: what Claude Code
writes, eccx reads, and vice versa.

If Node or the vault is unavailable we fall back to a plain markdown journal so
recall never hard-fails.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .util import ADAPTER_STATE, ECC_ROOT, ensure_ecc_deps

NODE_CLI = ECC_ROOT / "scripts" / "ecc.js"
JOURNAL = ADAPTER_STATE / "journal.jsonl"


def _node() -> str | None:
    return shutil.which("node")


def _available(auto_install: bool = False) -> bool:
    if not (_node() and NODE_CLI.is_file()):
        return False
    if (ECC_ROOT / "node_modules").is_dir():
        return True
    if auto_install:
        return ensure_ecc_deps()
    return False


def _run(args: list[str], cwd: Path, stdin: str | None = None) -> tuple[int, str, str]:
    try:
        p = subprocess.run([_node(), str(NODE_CLI), *args], cwd=str(cwd),
                           input=stdin, capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout, p.stderr
    except Exception as exc:
        return 1, "", str(exc)


def init(cwd: Path, scope: str = "project") -> str:
    if _available(auto_install=True):
        code, out, err = _run(["memory", "init", "--scope", scope], cwd)
        if code == 0:
            return out.strip() or "memory vault ready"
        return f"vault init failed, using journal: {err.strip()[:200]}"
    ADAPTER_STATE.mkdir(parents=True, exist_ok=True)
    JOURNAL.touch()
    return f"node/vault unavailable — journal fallback at {JOURNAL}"


def save(title: str, body: str, kind: str = "note", tags: list[str] | None = None,
         cwd: Path | None = None) -> dict:
    cwd = cwd or Path.cwd()
    if _available(auto_install=True):
        args = ["memory", "save", "--title", title, "--kind", kind,
                "--source-harness", "eccx", "--stdin"]
        for t in tags or []:
            args += ["--tag", t]
        code, out, err = _run(args, cwd, stdin=body)
        if code == 0:
            mid = ""
            for line in out.splitlines():
                if line.startswith("ID:"):
                    mid = line.split(":", 1)[1].strip()
            return {"ok": True, "backend": "ecc-vault", "id": mid, "raw": out.strip()}
        err_txt = err.strip()[:300]
    else:
        err_txt = "vault unavailable"
    ADAPTER_STATE.mkdir(parents=True, exist_ok=True)
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "title": title, "kind": kind, "tags": tags or [], "body": body}
    with JOURNAL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True, "backend": "journal", "id": "journal", "note": err_txt}


def search(query: str = "", cwd: Path | None = None, limit: int = 8,
           scope: str = "project") -> list[dict]:
    cwd = cwd or Path.cwd()
    out_records: list[dict] = []
    if _available():
        args = ["memory", "search", "--json", "--limit", str(limit), "--scope", scope]
        if query:
            args.insert(2, query)
        code, out, _err = _run(args, cwd)
        if code == 0 and out.strip():
            try:
                data = json.loads(out)
                for r in data.get("results", []):
                    m = r.get("memory", {})
                    out_records.append({
                        "id": m.get("id", ""),
                        "title": m.get("title", ""),
                        "kind": m.get("kind", "note"),
                        "trust": m.get("trust", ""),
                        "tags": m.get("tags", []),
                        "score": r.get("score"),
                        "body": (r.get("excerpt") or r.get("body") or "").strip(),
                        "backend": "ecc-vault",
                    })
            except json.JSONDecodeError:
                pass
    if not out_records and JOURNAL.exists():
        words = [w for w in query.lower().split() if len(w) > 2]
        for line in JOURNAL.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            hay = (rec.get("title", "") + " " + rec.get("body", "")).lower()
            if words and not any(w in hay for w in words):
                continue
            out_records.append({
                "id": "journal", "title": rec.get("title", ""),
                "kind": rec.get("kind", "note"), "trust": "local",
                "tags": rec.get("tags", []), "score": None,
                "body": rec.get("body", ""), "backend": "journal",
            })
        out_records = out_records[-limit:][::-1]
    return out_records


def read(mid: str, cwd: Path | None = None) -> dict | None:
    cwd = cwd or Path.cwd()
    if _available():
        code, out, _ = _run(["memory", "read", mid, "--json"], cwd)
        if code == 0 and out.strip():
            try:
                return json.loads(out)
            except json.JSONDecodeError:
                return None
    return None
