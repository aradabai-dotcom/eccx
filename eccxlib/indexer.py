"""Build and load the ECC component index.

Index v4 indexes *sections* (H2 blocks), not just documents. Whole-file retrieval
from a 311-skill catalogue means 80% of what you inject is off-topic; section
indexing lets the router inject the two paragraphs that actually answer the task.
Section text is never copied into the index — only (line_start, line_end, cost,
keywords) — so index.json stays ~1 MB and the source stays the single truth.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import frontmatter as fm
from .util import (ADAPTER_ROOT, ADAPTER_STATE, ECC_ROOT, est_tokens, load_json,
                   read_text, save_json, tokenize)

INDEX_PATH = ADAPTER_STATE / "index.json"
OVERLAY = ADAPTER_ROOT / "skills-local"
INDEX_VERSION = 8  # bump whenever tokenisation, paths or section splitting change
MAX_KWS = 16

H2 = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def split_sections(body: str) -> list[dict]:
    """Split a markdown body into H2 sections with line ranges."""
    lines = body.splitlines()
    starts = [i for i, ln in enumerate(lines) if H2.match(ln)]
    if not starts:
        return []
    out = []
    for n, idx in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        text = "\n".join(lines[idx:end])
        heading = H2.match(lines[idx]).group(1).strip()
        kws: dict[str, int] = {}
        for t in tokenize(text):
            kws[t] = kws.get(t, 0) + 1
        top = sorted(kws.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_KWS]
        out.append({
            "h": heading,
            "start": idx,
            "end": end,
            "tokens": est_tokens(text),
            "kws": " ".join(k for k, _ in top),
        })
    return out


def _doc(kind: str, cid: str, path: Path, root: Path, extra: dict | None = None) -> dict:
    text = read_text(path)
    meta, body = fm.split(text)
    name = meta.get("name") or cid
    desc = meta.get("description") or ""
    if not desc:
        desc = fm.first_paragraph(body)
    heads = fm.headings(body)
    sections = split_sections(body)
    return {
        "id": cid,
        "kind": kind,
        "name": name,
        "desc": " ".join(desc.split())[:600],
        "path": str(path.relative_to(root)),
        "headings": heads,
        "body_tokens": est_tokens(body),
        "sections": sections,
        "extra": extra or {},
    }


def build(root: Path = ECC_ROOT) -> dict:
    docs: list[dict] = []

    skills = root / "skills"
    if skills.is_dir():
        for d in sorted(skills.iterdir()):
            f = d / "SKILL.md"
            if f.is_file():
                docs.append(_doc("skill", d.name, f, root, {"dir": str(d.relative_to(root))}))

    agents = root / "agents"
    if agents.is_dir():
        for f in sorted(agents.glob("*.md")):
            meta, _ = fm.split(read_text(f))
            docs.append(_doc("agent", f.stem, f, root, {
                "tools": meta.get("tools", ""), "model": meta.get("model", "")}))

    commands = root / "commands"
    if commands.is_dir():
        for f in sorted(commands.glob("*.md")):
            meta, _ = fm.split(read_text(f))
            docs.append(_doc("command", f.stem, f, root, {
                "argument_hint": meta.get("argument-hint", "")}))

    rules = root / "rules"
    if rules.is_dir():
        for pack in sorted(p for p in rules.iterdir() if p.is_dir()):
            for f in sorted(pack.glob("*.md")):
                docs.append(_doc("rule", f"{pack.name}/{f.stem}", f, root,
                                 {"pack": pack.name}))

    for g in ("the-shortform-guide.md", "the-longform-guide.md", "the-security-guide.md"):
        p = root / g
        if p.is_file():
            docs.append(_doc("guide", p.stem, p, root))

    # Local overlay: components authored here for gaps the upstream catalogue
    # does not cover. Kept out of ~/ECC so `eccx sync` (git pull) can never
    # clobber them, and so upstream stays byte-identical to its origin.
    if OVERLAY.is_dir():
        for d in sorted(OVERLAY.iterdir()):
            f = d / "SKILL.md"
            if f.is_file():
                docs.append(_doc("skill", d.name, f, ADAPTER_ROOT,
                                 {"dir": f"skills-local/{d.name}", "origin": "local",
                                  "root": "adapter"}))

    readme = root / "README.md"
    if readme.is_file():
        text = read_text(readme)
        docs.append({
            "id": "README", "kind": "manual", "name": "ECC README",
            "desc": "Full ECC manual: install matrix, harness support, hooks, MCP, "
                    "troubleshooting. Large file — sections are indexed individually.",
            "path": "README.md", "headings": fm.headings(text, 60),
            "body_tokens": est_tokens(text), "sections": split_sections(text),
            "extra": {},
        })

    index = {
        "version": INDEX_VERSION,
        "ecc_root": str(root),
        "count": len(docs),
        "count_sections": sum(len(d["sections"]) for d in docs),
        "count_local": sum(1 for d in docs if d["extra"].get("origin") == "local"),
        "docs": docs,
    }
    save_json(INDEX_PATH, index)
    return index


def load(force: bool = False) -> dict:
    if not force:
        data = load_json(INDEX_PATH, None)
        if (isinstance(data, dict) and data.get("version") == INDEX_VERSION
                and data.get("docs")):
            return data
    return build()


def load_json_soft() -> dict | None:
    data = load_json(INDEX_PATH, None)
    if isinstance(data, dict) and data.get("version") == INDEX_VERSION:
        return data
    return None


def stats(index: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in index["docs"]:
        out[d["kind"]] = out.get(d["kind"], 0) + 1
    out["tokens_if_all_loaded"] = sum(d["body_tokens"] for d in index["docs"])
    out["sections"] = index.get("count_sections", 0)
    out["local"] = index.get("count_local", 0)
    return out
