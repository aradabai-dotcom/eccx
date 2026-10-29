"""Two-stage retrieval: lexical recall, then model rerank.

Why this module exists
----------------------
`router.py` ranks by vocabulary overlap. That caps out well below what a reader
with domain sense achieves: a query saying "make this function easier to read"
shares almost no tokens with `code-simplifier`, yet any engineer would pick it.

A reranker fixes exactly that class of error, but it costs tokens and latency, so
it must not run on every query. The design is a confidence-gated cascade:

    lexical (55 ms, 0 tokens)
        └─ confident? ── yes ──► return                       (no model)
                        └─ no  ──► shortlist N candidates (~400 tokens)
                                   └─ model orders them once (~120 tokens)
                                      └─ cached by (query, candidate set)

The model is the agent itself: `eccx rerank` emits a compact request, the agent
answers with an ordering, `--apply` validates and stores it. Every judgement is
cached, so a repeated query is free and an offline run can replay a whole set.

Trust rules
-----------
* `--apply` rejects ids that were not in the shortlist (no hindsight edits).
* A judgement is bound to the query and projected onto the *current* candidate
  set; it can only reorder components that were candidates when it was made.
* When several judgements exist for one query, the freshest at equal overlap
  wins — insertion order is never evidence.
* Partial orderings are allowed; unlisted candidates keep lexical order.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

from .util import ADAPTER_STATE, est_tokens, locked, save_json

CACHE = ADAPTER_STATE / "rerank-cache.json"
SHORTLIST_K = 15
DESC_CHARS = 105

# Gate thresholds, tuned on evals/routing.jsonl (dev set) and never on held-out.
# Trade-off measured there: (25, 0.30) skips 44% of queries at 91% precision on
# the skipped ones. Panels from a grid sweep are in docs/QUALITY.md.
GATE_MIN_SCORE = 25.0
GATE_MIN_GAP = 0.30


def card(doc: dict, n: int) -> str:
    desc = " ".join((doc.get("desc") or "").split())[:DESC_CHARS]
    return f"{n:>2}. {doc['kind']}:{doc['id']} — {desc}"


def shortlist(index: dict, query: str, k: int = SHORTLIST_K,
              ctx: list[str] | None = None, boost: dict | None = None) -> list[dict]:
    from . import router
    return router.score(index, query, top=k, project_context=ctx, boost=boost)


def gate(results: list[dict]) -> dict:
    """Is the lexical answer good enough to skip the model?"""
    if not results:
        return {"confident": False, "reason": "no candidates", "gap": 0.0}
    top = results[0]["score"]
    second = results[1]["score"] if len(results) > 1 else 0.0
    gap = (top - second) / top if top else 0.0
    confident = top >= GATE_MIN_SCORE and gap >= GATE_MIN_GAP
    reason = ("high score and clear margin" if confident
              else "low margin" if top >= GATE_MIN_SCORE else "weak top score")
    return {"confident": confident, "gap": round(gap, 3), "top_score": top,
            "reason": reason}


def _key(query: str, ids: list[str]) -> str:
    """Cache identity = normalised query + exact candidate set.

    Depth is *not* part of the key: a k=15 shortlist and a k=30 shortlist already
    hash differently because their id lists differ. Adding depth broke every
    judgement written before the escalation feature landed — a reminder that the
    cache key is a contract.
    """
    payload = json.dumps({"q": " ".join(query.lower().split()), "ids": ids},
                         sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def load_cache() -> dict:
    """Read the judgement cache; never lose it silently.

    Three outcomes, deliberately distinct:

      * no file      -> {} quietly (first run, nothing to report)
      * valid file   -> the dict
      * corrupt file -> move it aside to `<name>.corrupt` and shout on stderr

    The third case used to `return {}`. That made a truncated cache (power
    loss, full disk, a kill during write) indistinguishable from an empty one,
    and the *next* `save_cache` overwrote the evidence: 136 judgements gone
    with nothing in the logs. Preserving the file costs one rename and turns a
    silent 20-point routing regression into a one-line warning.
    """
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        spare = CACHE.with_name(CACHE.name + ".corrupt")
        try:
            CACHE.replace(spare)
        except OSError:
            spare = None
        print(f"[eccx] rerank cache unreadable ({exc.__class__.__name__}); "
              f"kept a copy at {spare or '(copy failed)'} and started empty. "
              "Re-judge, or restore the file by hand.", file=sys.stderr)
        return {}
    except OSError as exc:
        print(f"[eccx] cannot read rerank cache: {exc}", file=sys.stderr)
        return {}


def save_cache(cache: dict) -> None:
    """Atomic: a crash mid-write must not destroy 136 judgements.

    `save_json` writes a temp file and renames, so a full disk leaves the old
    cache intact. Reproduced before the fix: ENOSPC during `write_text` left a
    truncated file, `load_cache` returned {}, and the next save finished the
    job.
    """
    save_json(CACHE, cache, indent=0)


def lookup(query: str, ids: list[str]) -> dict | None:
    return load_cache().get(_key(query, ids))


def build_request(query: str, results: list[dict]) -> dict:
    """The compact thing the model has to read. This is the whole cost."""
    ids = [f"{r['doc']['kind']}:{r['doc']['id']}" for r in results]
    cards = "\n".join(card(r["doc"], i + 1) for i, r in enumerate(results))
    return {
        "query": query,
        "key": _key(query, ids),
        "candidates": ids,
        "cards": cards,
        "tokens": est_tokens(cards),
        "gate": gate(results),
    }


def apply_order(query: str, results: list[dict], order: list[str],
                source: str = "agent") -> dict:
    """Validate and store a judgement. Unknown ids are refused, not ignored."""
    ids = [f"{r['doc']['kind']}:{r['doc']['id']}" for r in results]
    unknown = [o for o in order if o not in ids]
    if unknown:
        raise ValueError(f"not in shortlist: {', '.join(unknown)}")
    status = "no_candidate" if not order else "ranked"
    deduped = list(dict.fromkeys(order))
    rest = [i for i in ids if i not in deduped]
    final = deduped + rest
    # Locked read-modify-write. Two `eccx rerank --apply` at once (two agents,
    # or a retry racing the original) both read the same snapshot and the
    # second save erases the first. Measured: 10 judgements written by 2
    # processes, 5 on disk. The lock is per cache file, so the cost is a
    # single open/flock on a path that is already being written.
    with locked(CACHE):
        cache = load_cache()
        cache[_key(query, ids)] = {
            "query": " ".join(query.lower().split()),
            "order": final,
            "status": status,
            "source": source,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        save_cache(cache)
    return {"key": _key(query, ids), "order": final, "status": status,
            "changed_top": final[0] != ids[0]}


MIN_OVERLAP = 0.70


def _project(query: str, results: list[dict],
             ) -> tuple[list[dict] | None, dict | None, bool]:
    """Returns (ordered, record, exact).

    `exact` is a *fact*, not an inference. It used to be derived from
    `coverage >= 1.0`, which is wrong whenever the stored judgement was made on
    a **superset** pool: judge at k=20, resolve at k=15, every current id was
    judged, coverage is 1.0 — and the cascade stopped on a projection while
    reporting `projected: False`. Measured with a 20/15 split, overlap 0.75,
    coverage 1.0.

    Coverage answers "did the judge see everything I am ranking"; exactness
    answers "is this the same pool". Both matter, neither implies the other.
    """
    """Find the best judgement for this query and project it onto today's pool.

    A judgement is expensive and must survive catalogue growth. Keying it on an
    exact candidate list meant every index change silently discarded it — three
    regressions in one session. Instead we keep the *preference list* and project
    it onto the current candidates:

      - ids that were judged keep their judged relative order;
      - ids that were never judged keep lexical order and are appended after.

    Safety is unchanged: a judgement can only reorder components that existed
    when it was made — no hindsight, no resurrecting a component that was never
    a candidate. If too little of the judged set survives (catalogue changed
    radically), the judgement is treated as stale and ignored.
    """
    cache = load_cache()
    ids = [f"{r['doc']['kind']}:{r['doc']['id']}" for r in results]
    hit = cache.get(_key(query, ids))
    if hit:
        ordered, rec = _apply(results, hit)
        return ordered, rec, True

    normalised = " ".join(query.lower().split())
    best, best_rank = None, None
    for rec in cache.values():
        if rec.get("query") != normalised:
            continue
        # `no_candidate` certifies "nothing in *that* pool answers this", which
        # says nothing about a different pool. Projecting it would let an old
        # empty verdict shadow a later, real ranking (measured: it silently
        # discarded the escalated judgement for 3 held-out queries). Only
        # `ranked` records carry an order worth projecting; `no_candidate` is
        # honoured solely on an exact candidate-set match, where it is what
        # triggers escalation.
        if rec.get("status") != "ranked":
            continue
        judged = rec.get("order") or []
        if not judged:
            continue
        overlap = len(set(judged) & set(ids)) / len(judged)
        # Ties are broken by recency, never by dict order. Two judgements can
        # legitimately exist for one query (an old shallow one and a new one
        # after the index moved); picking the insertion-order winner let a
        # stale judgement shadow a fresh one forever, which is how a re-judged
        # query silently kept answering with yesterday's ranking.
        rank = (round(overlap, 6), rec.get("at") or "", len(judged))
        if best_rank is None or rank > best_rank:
            best, best_rank = rec, rank
    if best and best_rank[0] >= MIN_OVERLAP:
        ordered, rec = _apply(results, best, partial=True)
        return ordered, rec, False
    return None, None, False


def _apply(results: list[dict], rec: dict, partial: bool = False):
    ids = [f"{r['doc']['kind']}:{r['doc']['id']}" for r in results]
    byid = dict(zip(ids, results))
    judged = [i for i in rec["order"] if i in byid]
    rest = [i for i in ids if i not in judged]
    if rec.get("status") == "no_candidate" and not partial:
        return None, rec
    return [byid[i] for i in judged + rest], rec


def reranked_results(query: str, results: list[dict]) -> tuple[list[dict], bool]:
    """Apply the best available judgement, projected onto the current pool."""
    ordered, rec, _exact = _project(query, results)
    if ordered is None:
        return results, False
    return ordered, True


# Retrieval depths, in cascade order. Measured prompt cost: ~510 tokens at
# k=15, ~1020 at k=30, ~1680 at k=50 (card text only). A query stops at the
# first depth where a judgement was made *for that exact pool* — anything else
# is a partial projection and keeps escalating. k=100 exists as a capability
# but was not made the default: on the dev set it buys nothing over 50.
DEPTHS = (15, 30, 50)


def _ids(results: list[dict]) -> list[str]:
    return [f"{r['doc']['kind']}:{r['doc']['id']}" for r in results]


def _overlap(rec: dict, ids: list[str]) -> float:
    """How much of the judged material still exists (staleness guard)."""
    judged = rec.get("order") or []
    return len(set(judged) & set(ids)) / len(judged) if judged else 0.0


def _coverage(rec: dict, ids: list[str]) -> float:
    """How much of today's pool the judgement actually saw (sufficiency guard).

    Two different questions, two different ratios. Overlap asks "is this
    judgement still about the catalogue?"; coverage asks "did whoever made it
    review every candidate I am about to rank?" A 5-candidate judgement can
    have overlap 1.0 and coverage 0.33 — it is safe to apply, but it is not
    proof that the right answer is among today's 15.
    """
    judged = set(rec.get("order") or [])
    return len(judged & set(ids)) / len(ids) if ids else 0.0


def resolve(index: dict, query: str, k: int = SHORTLIST_K, escalate_to: int = 30,
            ctx: list[str] | None = None, boost: dict | None = None,
            deep_to: int = 50,
            term_weights: dict[str, float] | None = None) -> tuple[list[dict], dict]:
    """Production policy: rerank at k, escalate while the evidence is partial.

    Trust rule, stated once and enforced here: a judgement is *conclusive* only
    at the depth it was made for (same candidate set, status `ranked`). A
    judgement projected onto a different pool is a best-effort reordering, good
    enough to fall back on but not good enough to stop the cascade — measured,
    the pool at k=30 can be missing the right answer while a partial projection
    still looks successful (one held-out query was answered with the 2nd choice
    for exactly that reason).

    So: walk 15 -> 30 -> 50, keep the deepest partial answer as a fallback, and
    return immediately on an exact match. A cold cache therefore costs one
    k=50 shortlist, not a wrong answer.
    """
    from . import router
    fallback: list[dict] | None = None
    first_projection: int | None = None
    meta = {"depth": k, "escalated": False, "judged_deeper": False,
            "status": "lexical", "steps": []}
    # Deduplicated *eagerly* and only upward: the comprehension used to test
    # `meta["steps"]` while building the list, so (15, 15, 15) produced three
    # entries — the guard was evaluated before the first append.
    depths: list[int] = []
    for d in (k, escalate_to, deep_to):
        if d and (not depths or d > depths[-1]):
            depths.append(d)
    if not depths:
        return [], meta

    for depth in depths:
        meta["steps"].append(depth)
        pool = router.score(index, query, top=depth, project_context=ctx,
                            boost=boost, term_weights=term_weights)
        ids = _ids(pool)
        ordered, rec, exact = _project(query, pool)
        meta["depth"] = depth
        if rec is None:
            continue
        status = rec.get("status", "ranked")
        coverage = _coverage(rec, ids)
        meta["status"] = status
        meta["overlap"] = round(_overlap(rec, ids), 3)
        meta["coverage"] = round(coverage, 3)
        if status == "ranked" and ordered is not None:
            # Conclusive only on an EXACT pool. `coverage >= 1.0` was the old
            # test and it is satisfiable by a judgement made on a superset
            # pool — a projection the cascade then trusted.
            if exact:
                meta["projected"] = False
                meta["escalated"] = len(meta["steps"]) > 1
                # `escalated` says the search was widened; it says nothing
                # about whether that bought anything. On a cold cache every
                # query escalates to the deepest pool, and `eccx eval --rerank`
                # printed 100 % escalation on every run — including runs where
                # no judgement existed at all. `judged_deeper` is the number
                # that answers "did widening actually find a judgement": here,
                # the judgement used was made at this depth, and this depth was
                # reached by widening.
                meta["judged_deeper"] = depth > k
                return ordered, meta
            fallback = ordered  # usable, but the pool it judged is not this one
            meta["projected"] = True
            if first_projection is None:
                first_projection = depth
    meta["escalated"] = len(meta["steps"]) > 1
    meta["judged_deeper"] = first_projection is not None and first_projection > k
    if fallback is not None:
        return fallback, meta
    deepest = router.score(index, query, top=meta["steps"][-1],
                           project_context=ctx, boost=boost,
                           term_weights=term_weights)
    return deepest, meta


def coverage(queries: list[str], index: dict, k: int = SHORTLIST_K) -> dict:
    total = len(queries)
    have = 0
    for q in queries:
        res = shortlist(index, q, k=k)
        ids = [f"{r['doc']['kind']}:{r['doc']['id']}" for r in res]
        if lookup(q, ids):
            have += 1
    return {"queries": total, "cached": have,
            "coverage": round(have / total, 3) if total else 0.0}
