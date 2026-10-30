"""Index an arbitrary directory of prose.

ECC's catalogue has a fixed shape: `skills/<id>/SKILL.md` with YAML
frontmatter. That is one corpus out of many, and everything downstream —
router, budget, evaluator, section scoring — never actually depended on it.
This module is what removes the last dependency: point it at a directory of
markdown and it produces the same index the router already knows how to read.

Design decisions, and why:

* **The directory *is* the taxonomy.** `kind` is the first path segment below
  the root (`notes/`, `invoices/`, `decisions/`). Inventing a taxonomy from
  content would be guesswork; the folder structure is the one thing an author
  has already stated on purpose.
* **The id is the relative path.** Stable across rebuilds, so an evaluation
  file written today still measures the same thing tomorrow. Renaming a file
  breaks its id — that is honest, and better than a hash that silently
  re-points to different text.
* **Headings, not a fixed depth.** H2 when present (ECC's convention, and what
  the section scorer was measured on), H1 otherwise, H3 for long documents
  that only use deeper levels. A 400-line note with no headings yields one
  section, and the router degrades to document-level similarity — visible in
  `corpus stats`, not hidden.
* **No text is copied.** Only offsets, token costs and keywords, exactly like
  the ECC index, so editing a note never invalidates the index by content,
  only by structure.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .util import est_tokens, read_text, tokenize

VERSION = 1
MAX_KWS = 16
SUFFIXES = (".md", ".markdown", ".mdx", ".txt")
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv",
             "venv", "dist", "build", "site-packages", ".mypy_cache",
             ".pytest_cache", ".eccx"}
MAX_BYTES = 2_000_000          # a 2 MB note is a data dump, not prose

H1 = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
H2 = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
H3 = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
FENCE = re.compile(r"^(```|~~~)", re.MULTILINE)

# Frontmatter handling is shared with the ECC indexer rather than reimplemented:
# two parsers that disagree is how a corpus gets indexed differently depending
# on which command you happened to run.
from . import frontmatter as fm  # noqa: E402


def slug(rel: str) -> str:
    """`notes/db/latency.md` -> `notes/db/latency`."""
    p = rel.rsplit(".", 1)[0] if "." in rel.rsplit("/", 1)[-1] else rel
    return "/".join(seg.strip() for seg in p.split("/") if seg.strip())


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "untitled"


def _choose_heading(text: str) -> re.Pattern:
    """H2 if the document has two or more, else H1, else H3.

    One H2 in a 300-line file is usually a stray; splitting on it would create
    one giant section and one fragment. Two is the smallest number that shows
    the author actually structures the document at that level.
    """
    if len(H2.findall(text)) >= 2:
        return H2
    if len(H1.findall(text)) >= 1:
        return H1
    if len(H3.findall(text)) >= 2:
        return H3
    return H2


def split_sections(text: str, pattern: re.Pattern | None = None) -> list[dict]:
    """Heading-delimited sections with line ranges, costs and keywords."""
    pat = pattern or _choose_heading(text)
    lines = text.splitlines()
    # Headings inside fenced code blocks are code, not structure. Counting them
    # turns a yaml example into a chapter.
    fenced, depth = set(), 0
    for i, ln in enumerate(lines):
        if FENCE.match(ln.strip()):
            depth ^= 1
        fenced.add(i) if depth else None
    starts = [i for i, ln in enumerate(lines)
              if pat.match(ln) and i not in fenced]
    if not starts:
        return []
    out = []
    for n, idx in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = "\n".join(lines[idx:end])
        kws: dict[str, int] = {}
        for t in tokenize(block):
            kws[t] = kws.get(t, 0) + 1
        top = sorted(kws.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_KWS]
        out.append({
            "h": pat.match(lines[idx]).group(1).strip(),
            "start": idx,
            "end": end,
            "tokens": est_tokens(block),
            "kws": " ".join(k for k, _ in top),
        })
    return out


def _title(text: str, body: str, rel: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if m:
        return m.group(1).strip()[:200]
    for line in body.splitlines():
        if line.strip():
            return line.strip()[:200]
    return Path(rel).stem


def _desc(body: str, limit: int = 600) -> str:
    para = fm.first_paragraph(body) or ""
    if not para:
        para = " ".join(body.split())[:400]
    return " ".join(para.split())[:limit]


def discover(root: Path) -> list[Path]:
    root = Path(root).expanduser().resolve()
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts[:-1]):
            continue
        try:
            if p.stat().st_size > MAX_BYTES:
                continue
        except OSError:
            continue
        out.append(p)
    return out


def build(root: Path, kinds: set[str] | None = None) -> dict:
    """Index every markdown/text file under `root`."""
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")
    docs, no_sections = [], []
    for path in discover(root):
        rel = path.relative_to(root).as_posix()
        try:
            text = read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        meta, body = fm.split(text)
        parts = rel.split("/")
        kind = _slugify(parts[0]) if len(parts) > 1 else "doc"
        if kinds and kind not in kinds:
            continue
        sections = split_sections(body)
        if not sections:
            no_sections.append(rel)
        desc = meta.get("description") or _desc(body)
        t = _title(text, body, rel)
        try:
            st = path.stat()
        except OSError:
            continue
        docs.append({
            "id": slug(rel),
            "size": st.st_size,
            "mtime": int(st.st_mtime),
            "kind": kind,
            "name": meta.get("name") or t,
            "desc": " ".join(desc.split())[:600],
            "path": rel,
            "headings": fm.headings(body),
            "body_tokens": est_tokens(body),
            "sections": sections,
            "extra": {"root": "corpus", "corpus": str(root)},
        })
    return {
        "version": VERSION,
        "root": str(root),
        "built": _fingerprint(root, docs),
        "counts": {
            "docs": len(docs),
            "sections": sum(len(d["sections"]) for d in docs),
            "without_sections": len(no_sections),
            "tokens": sum(d["body_tokens"] for d in docs),
        },
        "docs": docs,
    }


def _fingerprint(root: Path, docs: list[dict]) -> str:
    """Structure and cheap file identity: path, size, mtime.

    Deliberately *not* a content hash: `is_stale` runs on every `recall`, and
    re-reading a 2 500-file directory to answer "is my index fresh" costs more
    than the query it prepares. A same-size edit within the same second is
    therefore invisible — `corpus build` is the answer to that, and pretending
    otherwise would put a second of I/O on the hot path to catch a rare case.
    """
    h = hashlib.sha256()
    for d in docs:
        h.update(d["path"].encode())
        h.update(str(d.get("size", 0)).encode())
        h.update(str(d.get("mtime", 0)).encode())
        h.update(str(len(d["sections"])).encode())
    return h.hexdigest()[:16]


def fingerprint(index: dict) -> str:
    return _fingerprint(Path(index["root"]), index["docs"])


def stats(index: dict) -> dict:
    kinds: dict[str, int] = {}
    for d in index["docs"]:
        kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
    secs = [len(d["sections"]) for d in index["docs"]]
    return {
        "docs": len(index["docs"]),
        "sections": sum(secs),
        "tokens": sum(d["body_tokens"] for d in index["docs"]),
        "kinds": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
        "no_sections": sum(1 for n in secs if n == 0),
        "sections_per_doc": round(sum(secs) / max(1, len(secs)), 1),
        "median_tokens_per_doc": sorted(d["body_tokens"] for d in index["docs"])[
            len(index["docs"]) // 2] if index["docs"] else 0,
    }


def save(index: dict, state_dir: Path) -> Path:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    out = state_dir / "index.json"
    out.write_text(json.dumps(index, indent=0))
    return out


def load_from(state_dir: Path) -> dict:
    return json.loads((Path(state_dir) / "index.json").read_text())


def is_stale(index: dict) -> bool:
    """True if files were added, removed, resized or touched since the build."""
    root = Path(index["root"])
    if not root.is_dir():
        return True
    seen = {}
    for p in discover(root):
        try:
            st = p.stat()
        except OSError:
            continue
        seen[p.relative_to(root).as_posix()] = (st.st_size, int(st.st_mtime))
    for d in index["docs"]:
        cur = seen.get(d["path"])
        if cur is None or cur != (d.get("size"), d.get("mtime")):
            return True
    return len(seen) != len(index["docs"])
