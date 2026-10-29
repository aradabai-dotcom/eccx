"""Tolerant YAML-frontmatter reader for ECC markdown components.

ECC only uses a small subset of YAML in frontmatter: scalar keys, quoted
scalars, block scalars (> and |) and one nested mapping (metadata). We parse
that subset instead of pulling in a YAML dependency, and degrade to a
best-effort regex if a file is malformed.
"""
from __future__ import annotations

import re

FENCE = "---"


def split(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith(FENCE):
        return {}, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != FENCE:
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == FENCE:
            end = i
            break
    if end is None:
        return {}, text
    fm_lines = lines[1:end]
    body = "\n".join(lines[end + 1:])
    return _parse(fm_lines), body


def _parse(lines: list[str]) -> dict[str, str]:
    data: dict[str, str] = {}
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#") or line.startswith((" ", "\t")):
            i += 1
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*:\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, value = m.group(1), m.group(2).strip()
        if value in (">", "|", ">-", "|-", ">+", "|+"):
            block: list[str] = []
            i += 1
            while i < n and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            joined = (" " if value.startswith(">") else "\n").join(b for b in block if b)
            data[key] = joined.strip()
            continue
        if value.startswith(("\"", "'")) and len(value) >= 2:
            quote = value[0]
            if value.endswith(quote):
                value = value[1:-1]
            else:
                # multi-line quoted scalar: keep reading
                buf = [value[1:]]
                i += 1
                while i < n and not lines[i].rstrip().endswith(quote):
                    buf.append(lines[i].strip())
                    i += 1
                if i < n:
                    # `.strip()` matters: the closing line still carries its
                    # indentation, and joining it raw produced
                    # 'first part second part   third part' where YAML says
                    # 'first part second part third part' — a false js-yaml
                    # mismatch in `eccx validate`. Verified against PyYAML 6.
                    buf.append(lines[i].rstrip()[:-1].strip())
                value = " ".join(b for b in buf if b).strip()
                data[key] = value
                i += 1
                continue
            value = value.replace("\\\"", "\"").replace("\\'", "'")
        data[key] = value.strip()
        i += 1
    return data


HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.MULTILINE)


def headings(body: str, limit: int = 40) -> list[str]:
    return [m.group(2).strip() for m in HEADING_RE.finditer(body)][:limit]


def first_paragraph(body: str) -> str:
    """First meaningful prose line after frontmatter and any H1."""
    buf: list[str] = []
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("|") or s.startswith("```"):
            if buf:
                break
            continue
        if s.startswith((">", "-", "*", "1.")):
            if buf:
                break
            continue
        buf.append(s)
        if len(" ".join(buf)) > 220:
            break
    return " ".join(buf)[:300]
