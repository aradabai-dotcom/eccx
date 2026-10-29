#!/usr/bin/env python3
"""Ranking lab — try scoring variants without touching the product.

Why a separate harness: `router.score` is the thing being changed, so testing
variants in-place means the suite is red while the experiment runs. This file
re-implements the scoring loop with switches, measures every variant on the
*dev* set and on the *dirty held-out* sets separately, and is thrown away once a
variant is ported into `router.py` with its own test.

Separation matters more than convenience: a variant that lifts `routing.jsonl`
(the set the other parameters were tuned on) by 8 points and `heldout*.jsonl` by
0 has learned the dev set, not the task. The table prints both columns for that
reason.

    python3 tools/rank_lab.py                 # baseline + all variants
    python3 tools/rank_lab.py --only idf_cov  # one variant

`evals/heldout5.jsonl` is deliberately NOT loadable here. It is the final exam
and is measured once, by `eccx eval`, after the code is frozen.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eccxlib import indexer, router, util  # noqa: E402
from eccxlib.router import (CONTEXT_TOKENS, FIELD_WEIGHT, INTEGRATION_TOKENS,  # noqa: E402
                            KIND_PRIOR, expand_with_origin, _raw_name_parts)
from eccxlib.util import stem, tokenize  # noqa: E402

# Generic English fillers that carry no discriminative signal in a software
# catalogue. NOT query-specific: every entry is a function word or a verb of
# such general meaning that matching it says nothing about the topic.
# `nothing` -> stem `noth` won a query outright (`verify nothing regressed`),
# which is how this list was found.
STOP_EXTRA = {
    "never", "nothing", "none", "nobody", "always", "sometimes", "often", "again",
    "still", "yet", "already", "once", "twice", "really", "actually", "probably",
    "maybe", "perhaps", "these", "those", "their", "them", "its", "being", "been",
    "was", "were", "has", "have", "had", "having", "doing", "done", "going",
    "went", "come", "comes", "came", "like", "well", "back", "down", "out", "off",
    "away", "through", "around", "without", "within", "across", "behind",
    "toward", "upon", "up", "something", "anything", "everything", "way", "ways",
}

DEV = ROOT / "evals" / "routing.jsonl"
DIRTY = [ROOT / "evals" / f"heldout{n}.jsonl" for n in ("", "2", "3", "4")]


def load(paths):
    out = []
    for p in paths:
        for line in Path(p).read_text().splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def score_variant(index, query, top=50, *, qv=1, cov_floor=0.55, drop_numbers=False,
                  idf_cov=False, min_content=0, phrase="pair", fw=None, stop=False,
                  thes=False):
    """`qv` = query variant (1 = current query handling)."""
    docs = index["docs"]
    base = tokenize(query)
    if stop:
        base = [t for t in base if t not in STOP_EXTRA]
    if drop_numbers:
        base = [t for t in base if not t.isdigit() and t not in
                {"zero", "one", "two", "three", "four", "five", "first", "second", "third"}]
    if not base:
        return []
    saved_aliases = None
    if thes:
        saved_aliases = dict(router.ALIASES)
        for k, vs in THESAURUS.items():
            k2 = stem(k)
            router.ALIASES.setdefault(k2, [])
            for v in vs:
                if stem(v) not in router.ALIASES[k2]:
                    router.ALIASES[k2].append(stem(v))
    origin = expand_with_origin(base)
    qtokens = list(origin)
    syn_weight = {t: (1.0 if t in origin and t in base else 0.55) for t in qtokens}
    primary = set(base)
    global FIELD_WEIGHT
    saved = dict(FIELD_WEIGHT)
    if fw:
        FIELD_WEIGHT.update({"name": fw[0], "desc": fw[1], "heads": fw[2]})
    fields = [router._fields(d) for d in docs]
    n = len(docs)
    df = {}
    for t in set(qtokens):
        df[t] = sum(1 for f in fields
                    if any(t in f[k] for k in ("name", "desc", "heads")))

    def idf_of(t):
        return math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))

    primary_idf = sum(idf_of(t) for t in primary if t in df) or 1.0
    norm_query = " ".join(query.lower().split())
    results = []
    for doc, f in zip(docs, fields):
        s = 0.0
        matched = set()
        matched_idf = 0.0
        for t in qtokens:
            hit = 0.0
            if t in f["name"]:
                hit += FIELD_WEIGHT["name"]
            if t in f["desc"]:
                hit += FIELD_WEIGHT["desc"]
            if t in f["heads"]:
                hit += FIELD_WEIGHT["heads"]
            if t in f["extra"]:
                hit += FIELD_WEIGHT["extra"]
            if hit:
                s += idf_of(t) * hit * syn_weight.get(t, 0.55)
                matched.add(t)
                if t in primary:
                    matched_idf += idf_of(t)
        if not s:
            continue

        content = len(matched & primary)
        if min_content and content < min_content:
            s *= 0.5 ** (min_content - content)

        if idf_cov:
            cov = matched_idf / primary_idf
        else:
            covered = set()
            for t in matched:
                covered |= origin.get(t, set())
            cov = len(covered & primary) / max(1, len(primary))
        s *= cov_floor + (1 - cov_floor) * cov

        name_set = set(f["name"])
        s *= 1.0 + 0.15 * len(name_set & primary)
        if phrase == "pair":
            padded = f" {' '.join(f['name_seq'])} "
            for a, b_ in zip(qtokens, qtokens[1:]):
                if f"{a} {b_}" in padded:
                    s += 3.0

        raw = _raw_name_parts(doc) & INTEGRATION_TOKENS
        if raw and not (raw & (set(qtokens) | {stem(c) for c in []})):
            s *= 0.45
        foreign = (name_set & CONTEXT_TOKENS) - primary
        if foreign:
            s *= 0.38 if cov < 0.6 else 0.7
        if (name_set & CONTEXT_TOKENS) & primary:
            s *= 1.25
        desc_l = (doc.get("desc") or "").lower()
        name_flat = doc["name"].replace("-", " ")
        if norm_query and norm_query in name_flat:
            s += 14.0
        elif norm_query and norm_query in desc_l:
            s += 4.0
        s *= KIND_PRIOR.get(doc["kind"], 0.8)
        results.append((s, f"{doc['kind']}:{doc['id']}"))
    FIELD_WEIGHT.update(saved)
    if saved_aliases is not None:
        router.ALIASES.clear(); router.ALIASES.update(saved_aliases)
    results.sort(key=lambda r: (-r[0], r[1]))
    return results[:top]


def evaluate_variant(index, golden, **kw):
    known = {f"{d['kind']}:{d['id']}" for d in index["docs"]}
    h1 = h3 = h50 = n = 0
    for case in golden:
        exp = [e for e in case["expect"] if e in known]
        if not exp:
            continue
        n += 1
        ids = [i for _, i in score_variant(index, case["q"], top=50, **kw)]
        ranks = [ids.index(e) + 1 for e in exp if e in ids]
        if not ranks:
            continue
        r = min(ranks)
        h50 += 1
        h1 += r == 1
        h3 += r <= 3
    return {"n": n, "r1": h1 / n, "r3": h3 / n, "r50": h50 / n}


# General software vocabulary, written from the domain, not from failures:
# nominalisations (`deploy`/`deployment`), and word pairs any developer would
# call the same thing (`credential`/`secret`, `CVE`/`vulnerability`).
# `ALIASES` already covers abbreviations (pr, db, k8s, a11y); this covers the
# vocabulary gap that remains when a user describes a *situation* and the
# catalogue describes a *practice*.
THESAURUS = {
    "secret": ["credential"], "credential": ["secret"],
    "cve": ["vulnerability", "security", "advisory"],
    "vulnerability": ["cve", "advisory"], "advisory": ["cve", "vulnerability"],
    "typo": ["lint", "style", "format"], "lint": ["typo", "format", "static"],
    "unused": ["dead", "lint"], "format": ["lint", "style"],
    "duplicate": ["duplication", "reuse", "refactor"],
    "duplication": ["duplicate", "refactor"], "reuse": ["duplicate"],
    "cleanup": ["clean", "prune", "refactor"], "prune": ["cleanup", "stale"],
    "usage": ["reference", "occurrence"],
    "reference": ["usage", "occurrence"], "occurrence": ["usage", "reference"],
    "decision": ["decide", "adr", "rationale"], "decide": ["decision", "adr"],
    "rationale": ["decision", "adr"], "adr": ["decision", "architecture"],
    "deploy": ["deployment", "release", "ship"], "deployment": ["deploy", "release"],
    "release": ["deploy", "ship", "publish"],
    "migrate": ["migration"], "migration": ["migrate", "schema"],
    "schema": ["migration"],
    "learn": ["learning", "memory", "retain"], "learning": ["learn", "memory"],
    "memory": ["remember", "retain"],
    "remember": ["memory", "retain"], "forgot": ["memory", "retain"],
    "cost": ["spend", "price"], "spend": ["cost", "budget"],
    "budget": ["cost"], "price": ["cost", "billing"],
    "billing": ["invoice", "payment", "cost"], "invoice": ["billing", "payment"],
    "loop": ["repeat", "iteration", "autonomous"], "repeat": ["loop", "again"],
    "iteration": ["loop", "repeat"], "autonomous": ["loop", "agent"],
    "onboarding": ["newcomer", "understand", "explore"],
    "explore": ["onboarding", "navigate"],
    "outdated": ["stale", "drift", "sync"], "stale": ["outdated", "drift"],
    "drift": ["outdated", "sync", "drift"],
    "silent": ["silently", "swallow", "ignore"], "loudly": ["raise", "fail"],
    "typo": ["lint", "spelling"],
    "unreviewed": ["review", "stale"], "review": ["reviewer", "pr"],
    "goroutine": ["concurrency", "leak"],
    "concurrency": ["race", "parallel", "async"],
    "incident": ["oncall", "outage", "runbook"],
    "runbook": ["incident", "oncall", "playbook"],
    "playbook": ["runbook", "incident"],
    "hotfix": ["patch", "rollback"], "rollback": ["revert", "hotfix"],
    "observability": ["logging", "metrics", "tracing"],
    "logging": ["log", "observability"], "tracing": ["observability", "trace"],
}

VARIANTS = {
    "thes": {"thes": True},
    "thes+min2": {"thes": True, "min_content": 2},
    "thes+fw35": {"thes": True, "fw": (3.5, 2.2, 0.70)},
    "thes+fw30": {"thes": True, "fw": (3.0, 2.5, 0.80)},
    "thes+idf_cov35": {"thes": True, "idf_cov": True, "cov_floor": 0.35},
    "thes+idf_cov_hard": {"thes": True, "idf_cov": True, "cov_floor": 0.0},
    "thes+stop": {"thes": True, "stop": True},
    "thes+stop+min2": {"thes": True, "stop": True, "min_content": 2},
    "fw_35": {"fw": (3.5, 2.2, 0.70)},
    "fw_30": {"fw": (3.0, 2.5, 0.80)},
    "fw_25": {"fw": (2.5, 2.5, 1.00)},
    "stop": {"stop": True},
    "stop+fw_30": {"stop": True, "fw": (3.0, 2.5, 0.80)},
    "stop+fw_35": {"stop": True, "fw": (3.5, 2.2, 0.70)},
    "stop+min2": {"stop": True, "min_content": 2},
    "stop+fw_30+min2": {"stop": True, "fw": (3.0, 2.5, 0.80), "min_content": 2},
    "baseline": {},
    "idf_cov": {"idf_cov": True},
    "idf_cov_soft": {"idf_cov": True, "cov_floor": 0.35},
    "idf_cov_hard": {"idf_cov": True, "cov_floor": 0.0},
    "no_numbers": {"drop_numbers": True},
    "min2": {"min_content": 2},
    "idf_cov+no_numbers": {"idf_cov": True, "drop_numbers": True},
    "idf_cov35+no_numbers+min2": {"idf_cov": True, "cov_floor": 0.35,
                                  "drop_numbers": True, "min_content": 2},
    "idf_cov35+no_numbers": {"idf_cov": True, "cov_floor": 0.35,
                             "drop_numbers": True},
}


def main(argv):
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    idx = indexer.load()
    dev = load([DEV])
    dirty = load(DIRTY)
    print(f"dev {len(dev)} requêtes · inédit (sale) {len(dirty)} requêtes\n")
    print(f"{'variante':28s} {'dev@1':>7} {'dev@3':>7} {'hold@1':>7} {'hold@3':>7} {'plafond':>8}")
    base = None
    for name, kw in VARIANTS.items():
        if only and name != only and name != "baseline":
            continue
        d = evaluate_variant(idx, dev, **kw)
        h = evaluate_variant(idx, dirty, **kw)
        if name == "baseline":
            base = (d, h)
        mark = ""
        if base and name != "baseline":
            mark = f"  ({h['r1']-base[1]['r1']:+.1%} inédit)"
        print(f"{name:28s} {d['r1']:7.1%} {d['r3']:7.1%} {h['r1']:7.1%} {h['r3']:7.1%} {h['r50']:8.1%}{mark}")


if __name__ == "__main__":
    main(sys.argv[1:])
