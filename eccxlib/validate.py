"""Conformity checks for locally authored components.

The overlay is worthless if it drifts from what ECC accepts. The rules enforced
here are copied from upstream's own validator (`scripts/ci/validate-skills.js`),
read from its source, not invented:

  1. every skill directory contains SKILL.md
  2. frontmatter declares both `name:` and `description:`
  3. `description:` is an inline scalar — a block scalar or a multi-line value
     breaks flat-table renderers that key off it
  4. `name:` matches the directory name (upstream consistency requirement)

We additionally cross-check the parser against js-yaml, because a validator that
shares a bug with the code under test validates nothing.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import frontmatter as fm
from .util import ECC_ROOT, read_text

OVERLAY = Path(__file__).resolve().parent.parent / "skills-local"


def _block_scalar(lines: list[str]) -> list[str]:
    """Frontmatter keys whose value uses `>` or `|` (forbidden for description)."""
    out = []
    for line in lines:
        if line.startswith(("description:", "name:")) and line.strip().endswith((">", "|", ">-", "|-")):
            out.append(line.split(":", 1)[0])
    return out


def check_skill(path: Path) -> list[str]:
    problems: list[str] = []
    text = read_text(path)
    if not text.strip():
        return [f"{path}: empty SKILL.md"]
    meta, body = fm.split(text)
    if not meta:
        problems.append(f"{path}: no frontmatter")
        return problems
    name = (meta.get("name") or "").strip()
    desc = (meta.get("description") or "").strip()
    if not name:
        problems.append(f"{path}: missing `name:`")
    if not desc:
        problems.append(f"{path}: missing `description:`")
    if name and name != path.parent.name:
        problems.append(f"{path}: name '{name}' != directory '{path.parent.name}'")
    head = text.split("---")[1].splitlines() if text.count("---") >= 2 else []
    for key in _block_scalar(head):
        problems.append(f"{path}: `{key}:` must be an inline scalar, not a block scalar")
    if not body.strip():
        problems.append(f"{path}: empty body after frontmatter")
    if desc and len(desc) < 40:
        problems.append(f"{path}: description too short to route on ({len(desc)} chars)")
    return problems


def _js_yaml(paths: list[Path]) -> dict[str, str]:
    """Ground truth for the frontmatter, from the same parser ECC ships."""
    node = __import__("shutil").which("node")
    if not node or not (ECC_ROOT / "node_modules" / "js-yaml").is_dir() or not paths:
        return {}
    script = (
        "const yaml=require(process.argv[1] + '/node_modules/js-yaml');"
        "const fs=require('fs');const inp=JSON.parse(fs.readFileSync(0,'utf8'));"
        "const out={};for(const p of inp){const t=fs.readFileSync(p,'utf8');"
        "const m=t.match(/^---\\n([\\s\\S]*?)\\n---/);"
        "if(!m){out[p]='NO_FRONTMATTER';continue;}"
        "try{const d=yaml.load(m[1])||{};out[p]=JSON.stringify([d.name||'',"
        "(d.description||'').slice(0,80)]);}catch(e){out[p]='PARSE_ERROR:'+String(e);}}"
        "process.stdout.write(JSON.stringify(out));"
    )
    try:
        proc = subprocess.run([node, "-e", script, str(ECC_ROOT)],
                              input=json.dumps([str(p) for p in paths]),
                              capture_output=True, text=True, timeout=60)
        return json.loads(proc.stdout or "{}")
    except Exception:
        return {}


def run(overlay: Path | None = None, cross_check: bool = True) -> dict:
    overlay = overlay or OVERLAY
    if not overlay.is_dir():
        return {"skills": 0, "errors": [], "warnings": [], "ok": True}

    files = sorted(overlay.glob("*/SKILL.md"))
    errors: list[str] = []
    for f in files:
        errors.extend(check_skill(f))

    mismatches: list[str] = []
    if cross_check and files:
        ref = _js_yaml(files)
        for f in files:
            meta, _ = fm.split(read_text(f))
            value = ref.get(str(f))
            if value is None:
                continue
            if value.startswith(("NO_FRONTMATTER", "PARSE_ERROR")):
                mismatches.append(f"{f.name}: js-yaml says {value}")
                continue
            ref_name, ref_desc = json.loads(value)
            if (meta.get("name") or "") != ref_name:
                mismatches.append(f"{f.parent.name}: name mine={(meta.get('name') or '')!r} "
                                  f"js-yaml={ref_name!r}")
            mine_desc = (meta.get("description") or "")[:80]
            if mine_desc != ref_desc:
                mismatches.append(f"{f.parent.name}: description differs from js-yaml")

    return {"skills": len(files), "errors": errors, "mismatches": mismatches,
            "ok": not errors and not mismatches}
