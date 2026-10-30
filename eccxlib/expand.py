"""Query expansion — the recall half of the problem.

The reranker fixed ranking but could only reach the vocabulary the first stage
already retrieved: 7 of 30 held-out queries had no viable candidate at all.
The failures are linguistic, not semantic:

    "maintain"      vs  "maintainability"      (morphology)
    "where used"    vs  "walkthrough"          (synonymy)
    "regressed"     vs  "verification"         (domain vocabulary)

Rocchio's pseudo-relevance feedback fixes exactly that: assume the top few
results are partially relevant, and blend their distinguishing vocabulary into
the query.

    q' = α·q + β·Σ(weight · terms(top docs))  −  γ·terms(junk docs)

Two failure modes are known and must be defended against:

1. **Topic drift.** Expanding from a wrong top-1 drags the query further away.
   Defence: expand only from the *name and description* of the top docs, never
   their body; cap β well below α; and refuse terms that only appear in
   third-party-integration names (the `x-api` class of error).
2. **Junk terms.** Generic words ("file", "use", "code") inflate every document
   equally. Defence: document-frequency band — a term must be rare enough to
   discriminate (not in >12% of the catalogue) and common enough to exist in
   more than one document.
"""
from __future__ import annotations

import math
from collections import Counter

from .util import STOP, tokenize

MAX_DF_RATIO = 0.12
MIN_DF = 2

# Words that survive a document-frequency band but carry no topical signal.
# They are grammatical debris *of the descriptions*, not of the query — which is
# why this list lives here and not in the router's STOP (that one is frozen, so
# the measured baseline stays comparable).
EXPANSION_JUNK = {
    "they", "them", "their", "there", "these", "those", "wheth", "were",
    "was", "has", "have", "had", "being", "been", "does", "did", "doing", "done",
    "prefer", "preferably", "follow", "following", "example", "examples",
    "use", "used", "uses", "using", "includ", "want", "wants",
    "need", "needs", "requir", "requirement", "also", "instead",
    "without", "within", "across", "under", "over", "into", "from", "that",
    "your", "you", "will", "must", "should", "could", "would", "may", "might",
    "thing", "things", "way", "ways", "time", "times", "one", "two", "both",
    "each", "other", "others", "such", "same", "own", "more", "most", "less",
    "very", "just", "only", "even", "still", "well", "good", "better", "best",
    "new", "old", "first", "last", "next", "then", "than", "when", "where",
    "which", "while", "what", "whose", "whom", "how", "why", "all", "any",
    "can", "cannot", "not", "now", "here", "above", "below", "before", "after",
}


def _vocab(index: dict) -> tuple[Counter, int]:
    """Document frequency over (name + description) — cached on the index dict."""
    cache = index.get("__df__")
    if cache:
        return Counter(cache), index.get("__n__", 0)
    df: Counter = Counter()
    for d in index["docs"]:
        toks = set(tokenize(d["name"].replace("-", " ")))
        toks |= set(tokenize(d.get("desc") or ""))
        for t in toks:
            df[t] += 1
    index["__df__"] = dict(df)
    index["__n__"] = len(index["docs"])
    return df, len(index["docs"])


def _doc_terms(doc: dict) -> dict[str, float]:
    """Weighted vocabulary of one document: names matter more than prose."""
    out: dict[str, float] = {}
    for t in tokenize(doc["name"].replace("-", " ").replace("_", " ")):
        out[t] = out.get(t, 0.0) + 2.0
    for t in tokenize(doc.get("desc") or ""):
        out[t] = out.get(t, 0.0) + 1.0
    return out


def build_terms(index: dict, query: str, k_docs: int = 3, beta: float = 0.30,
                max_terms: int = 8, gamma: float = 0.0,
                consensus: bool = True, name_only: bool = True) -> dict:
    """Rocchio pseudo-relevance feedback.

    Returns {"weights": {term: weight}, "added": [...], "seed": [...]}.
    `alpha` is implicit: original terms keep weight 1.0 and everything added is
    scaled by `beta`.
    """
    from . import router

    base_tokens = tokenize(query)
    if not base_tokens:
        return {"weights": {}, "added": [], "seed": []}
    weights: dict[str, float] = {}
    for t in base_tokens:
        weights[t] = max(weights.get(t, 0.0), 1.0)

    seeds = router.score(index, query, top=k_docs)
    if not seeds:
        return {"weights": weights, "added": [], "seed": []}

    df, n = _vocab(index)
    max_df = max(MIN_DF + 1, int(n * MAX_DF_RATIO))
    primary = set(base_tokens)

    # Integrations are only legitimate when the user named them.
    from .router import INTEGRATION_TOKENS
    allowed_integration = INTEGRATION_TOKENS & primary

    # Consensus filter: a term must appear in at least two of the seed
    # documents. Expanding from a single (possibly wrong) document is the main
    # source of topic drift.
    support: Counter = Counter()
    per_doc = [_doc_terms(r["doc"]) for r in seeds]
    for dt in per_doc:
        for t in dt:
            support[t] += 1

    pool: Counter = Counter()
    for rank, _seed in enumerate(seeds):
        rank_weight = 1.0 / (1 + rank)
        source = name_only and {t: w for t, w in per_doc[rank].items() if w >= 2.0} \
            or per_doc[rank]
        for t, w in source.items():
            if t in primary or t in STOP or t in EXPANSION_JUNK or len(t) < 3:
                continue
            if t in INTEGRATION_TOKENS and t not in allowed_integration:
                continue
            d = df.get(t, 0)
            if d < MIN_DF or d > max_df:
                continue
            if consensus and support.get(t, 0) < 2:
                continue
            idf = math.log(1 + (n - d + 0.5) / (d + 0.5))
            pool[t] += rank_weight * w * idf

    if gamma > 0:
        # Negative feedback from the tail of the shortlist (classic Rocchio γ).
        tail = router.score(index, query, top=k_docs * 4)[k_docs * 4 - k_docs:]
        for r in tail:
            for t in _doc_terms(r["doc"]):
                if t in pool:
                    pool[t] -= gamma * pool[t] * 0.3

    added = [t for t, _ in pool.most_common(max_terms) if pool[t] > 0]
    if added:
        top = pool[added[0]] or 1.0
        for t in added:
            weights[t] = beta * (pool[t] / top) ** 0.5
    return {"weights": weights, "added": added,
            "seed": [f"{r['doc']['kind']}:{r['doc']['id']}" for r in seeds]}
