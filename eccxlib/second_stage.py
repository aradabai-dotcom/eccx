"""Second stage: semantic re-scoring of a lexical shortlist, gated.

Why a gate
----------
The bi-encoder (`semantic.py`) costs ~8 ms per query and holds a 273 MB model in
memory. Paying that on every query to reorder candidates the lexical stage
already separates cleanly is waste — the product is sold on latency and tokens.
The second stage therefore runs only when the first stage is **uncertain**: when
its top two candidates sit within `GATE_MARGIN` of each other.

What was tried first, and why it is not here
--------------------------------------------
Before the semantic stage, a *lexical* reranker was written and measured: query
coverage weighted by idf, name coverage, description coverage, a "shared terms
only through the name" penalty, multiplicative and additive blends, windows of
5 / 10 / 20 — thirty-six configurations. None beat the first stage, most lost
one or two points at rank 1, and the name-only penalty never fired once (0 of
400 candidates: descriptions share those words too).

The misses were not of the ordering kind. Three of eleven had no answer in the
top 20 at all: `github-ops` does not contain "pipeline", `security-scan` does
not contain "committed key". No reranker promotes a document that was never
retrieved. That is a *recall* problem, which is why the second stage re-scores
with semantic similarity instead of lexical features.

Honest limit
------------
The model is English-only. A French query embeds into noise (measured: the
expected document sat at rank 113 and 127), so the gate never escalates a French
query. Stage one's lexicon is the only bridge across languages, and it is
lexical.
"""
from __future__ import annotations

GATE_MARGIN = 0.20     # escalate when (s1 - s2) / s1 < this
WINDOW = 20            # candidates re-scored
ALPHA = 3.0            # cosine weight, same scale as `score_hybrid`


def uncertain(results: list[dict], margin: float = GATE_MARGIN) -> bool:
    """True when the first stage does not clearly separate its top two."""
    if len(results) < 2:
        return False
    first, second = results[0]["score"], results[1]["score"]
    if first <= 0:
        return False
    return (first - second) / first < margin


def apply_gate(results: list[dict], query_vector, matrix, doc_row: dict[str, int],
               *, alpha: float = ALPHA, window: int = WINDOW,
               margin: float = GATE_MARGIN) -> tuple[list[dict], bool]:
    """Re-score the shortlist by cosine. Returns (results, escalated).

    `doc_row` maps `"kind:id"` to the document's row in `matrix`. It is *not*
    the candidate's position in `results`: the matrix is built over the whole
    catalogue and never filtered, so using the result position would score every
    candidate against another document's vector — silently, and with plausible
    numbers.
    """
    if not uncertain(results, margin):
        return list(results), False
    if query_vector is None or matrix is None:
        return list(results), False
    head = results[:window]
    if len(head) < 2:
        return list(results), False

    rows = []
    for r in head:
        row = doc_row.get(f"{r['doc']['kind']}:{r['doc']['id']}")
        if row is None or row >= len(matrix):
            return list(results), False
        rows.append(row)

    best = head[0]["score"] or 1.0
    scored = []
    for pos, (r, row) in enumerate(zip(head, rows, strict=True)):
        cos = float(matrix[row] @ query_vector)
        scored.append((r["score"] / best + alpha * cos, pos, r, cos))
    scored.sort(key=lambda t: (-t[0], t[1]))

    out = []
    for blended, _pos, r, cos in scored:
        item = dict(r)
        item["score_lexical"] = r["score"]
        item["score"] = round(blended, 3)
        item["semantic"] = round(cos, 3)
        item["stage"] = 2
        out.append(item)
    return out + results[window:], True
