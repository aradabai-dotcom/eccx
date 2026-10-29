#!/usr/bin/env python3
"""Differential discrimination instrument — settle 5-point effects.

The problem it solves: 165 held-out queries give a +/- 7 point confidence
interval on recall@1, so every "improvement" of 3-5 points is indistinguishable
from noise. Nothing in this project could be decided on that instrument, and
several wrong conclusions were drawn from it.

Where the statistical power comes from — two independent sources:

  1. **Pairs instead of hits.** One query contributes one binary outcome to
     recall@1. The same query contributes `k` pairwise outcomes ("is the right
     document ranked above this distractor?"). With 10 distractors, 600 source
     documents give ~6 000 paired trials.
  2. **A corpus that is its own ground truth.** The 607 components come with a
     name and a description. A query built from a description *should* retrieve
     that component and not its nearest neighbour — no annotation, no author
     bias, and a new sample can be drawn for every experiment.

What it deliberately does NOT claim:

  * **The absolute number is not an accuracy.** The synthetic query shares words
    with its source document, so lexical scores run high and the absolute
    pairwise accuracy is optimistic. It is a *differential* instrument: it
    answers "does A beat B, and by how much", on the same trials. Any decision
    taken here must be confirmed on real held-out queries; this instrument makes
    experiments cheap enough to run, it does not replace the exam.
  * **Distractors are nearest neighbours by embedding**, so the pairs are
    deliberately hard — which is the regime the router actually fails in.

Usage:
    python3 tools/differential.py validate     # does it reproduce known truth?
    python3 tools/differential.py train        # learned ranker from synthetic pairs
    python3 tools/differential.py compare      # A/B with cluster bootstrap
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eccxlib import indexer, router, semantic  # noqa: E402
from eccxlib.util import tokenize  # noqa: E402

N_DISTRACTORS = 10
QUERY_WORDS = 6


def catalogue():
    idx = indexer.load()
    docs = idx["docs"]
    D = semantic.load_vectors(docs)
    return idx, docs, D


def synth_queries(docs, seed=0, exclude_names=True):
    """One query per document, built from its description.

    `exclude_names` drops words that appear in the component's own name: a query
    containing the name would be a spelling test, not a retrieval test.
    """
    rng = random.Random(seed)
    out = []
    for i, d in enumerate(docs):
        words = [w for w in tokenize((d.get("desc") or "")) if len(w) > 3]
        if exclude_names:
            own = set(tokenize(d["name"].replace("-", " ")))
            words = [w for w in words if w not in own]
        if len(words) < QUERY_WORDS:
            words = [w for w in tokenize((d.get("desc") or "")) if len(w) > 3]
        if len(words) < 3:
            continue
        picked = rng.sample(words, min(QUERY_WORDS, len(words)))
        out.append((i, " ".join(picked)))
    return out


def distractor_sets(D, docs, n=N_DISTRACTORS):
    """Nearest neighbours by embedding: the pairs that matter."""
    sims = D @ D.T
    np.fill_diagonal(sims, -2.0)
    order = np.argsort(-sims, axis=1)
    return {i: list(order[i][:n]) for i in range(len(docs))}


def trials(systems: dict, seed=0):
    """For each (source doc, distractor), the winner under each system.

    Returns {(doc, distractor): {system: won}} — the pairing is what gives the
    power: every system is scored on identical trials, so only the *difference*
    enters the variance.
    """
    idx, docs, D = catalogue()
    dist = distractor_sets(D, docs)
    qs = synth_queries(docs, seed=seed)
    keys = [f"{d['kind']}:{d['id']}" for d in docs]
    out = {}
    for i, q in qs:
        order = {}
        for name, fn in systems.items():
            ranked = fn(idx, q, D)
            order[name] = {k: r for r, k in enumerate(ranked)}
        for j in dist[i]:
            key = (i, j)
            row = {}
            for name in systems:
                a = order[name].get(keys[i])
                b = order[name].get(keys[j])
                if a is None:
                    row[name] = False
                elif b is None:
                    row[name] = True
                else:
                    row[name] = a < b
            out[key] = row
    return out


def cluster_bootstrap(rows, clusters, B=2000, seed=7):
    """CI over *source documents*, not over pairs.

    Pairs from one document are correlated (same distractor family, same
    query vocabulary). Resampling pairs would understate the interval by a wide
    margin and manufacture significance — the exact failure this file exists to
    avoid.
    """
    rng = random.Random(seed)
    by_cluster = {}
    for (i, j), v in rows.items():
        by_cluster.setdefault(i, []).append(v)
    ids = list(by_cluster)
    means = []
    for _ in range(B):
        sample = [ids[rng.randrange(len(ids))] for _ in ids]
        vals = [v for c in sample for v in by_cluster[c]]
        means.append(sum(vals) / len(vals))
    means.sort()
    return means[int(0.025 * B)], means[int(0.975 * B) - 1]


def paired_test(rows, a, b, clusters):
    """Paired bootstrap of the *difference*, clustered by source document."""
    rng = random.Random(11)
    by_cluster = {}
    for (i, j), v in rows.items():
        by_cluster.setdefault(i, []).append(v[a] - v[b])
    ids = list(by_cluster)
    diffs = []
    for _ in range(4000):
        sample = [ids[rng.randrange(len(ids))] for _ in ids]
        vals = [d for c in sample for d in by_cluster[c]]
        diffs.append(sum(vals) / len(vals))
    diffs.sort()
    lo, hi = diffs[int(0.025 * 4000)], diffs[int(0.975 * 4000) - 1]
    point = sum(d for v in by_cluster.values() for d in v) / sum(len(v) for v in by_cluster.values())
    wins = sum(1 for v in rows.values() if v[a] and not v[b])
    losses = sum(1 for v in rows.values() if v[b] and not v[a])
    return point, lo, hi, wins, losses


# ------------------------------------------------------------------ systems

def sys_lexical(idx, q, D):
    return [f"{r['doc']['kind']}:{r['doc']['id']}" for r in router.score(idx, q, top=60)]


def sys_hybrid(idx, q, D):
    qv = semantic.embed_query(q)
    return [f"{r['doc']['kind']}:{r['doc']['id']}"
            for r in router.score_hybrid(idx, q, top=60, vector_matrix=D, query_vector=qv)]


def sys_semantic_only(idx, q, D):
    qv = semantic.embed_query(q)
    order = np.argsort(-(D @ qv))
    return [f"{idx['docs'][i]['kind']}:{idx['docs'][i]['id']}" for i in order]


def sys_hybrid_alpha(idx_marker):
    def fn(idx, q, D):
        qv = semantic.embed_query(q)
        return [f"{r['doc']['kind']}:{r['doc']['id']}"
                for r in router.score_hybrid(idx, q, top=60, vector_matrix=D,
                                             query_vector=qv, alpha=idx_marker)]
    return fn


def main(argv):
    cmd = argv[0] if argv else "validate"

    if cmd == "validate":
        print("Validation de l'instrument : reproduit-il une vérité déjà connue ?")
        print("  vérité : hybride > lexical (+7,3 @3 sur 165 requêtes, p=0,016)\n")
        systems = {"lexical": sys_lexical, "hybride": sys_hybrid,
                   "semantique_seul": sys_semantic_only}
        rows = trials(systems)
        clusters = {i for i, _ in rows}
        print(f"  {len(rows)} paires sur {len(clusters)} documents sources\n")
        for name in systems:
            m = sum(1 for v in rows.values() if v[name]) / len(rows)
            lo, hi = cluster_bootstrap({k: v[name] for k, v in rows.items()}, clusters)
            print(f"  {name:16s} {m:6.1%}  IC95 [{lo:5.1%} ; {hi:5.1%}]")
        print()
        for a, b in (("hybride", "lexical"), ("hybride", "semantique_seul")):
            p, lo, hi, w, l = paired_test(rows, a, b, clusters)
            sig = "SIGNIFICATIF" if (lo > 0 or hi < 0) else "non significatif"
            print(f"  {a} - {b} : {p:+.1%}  IC95 [{lo:+.1%} ; {hi:+.1%}]  "
                  f"({w} paires gagnées / {l} perdues) -> {sig}")
        return 0

    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
