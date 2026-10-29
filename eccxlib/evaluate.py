"""Routing quality bar.

A router without a measured baseline is an opinion. This runs a golden set of
real intents against the index and reports recall@1/@3/@5 and MRR, plus the
exact failures so regressions are caught instead of felt.

Golden entries name several acceptable targets (`expect`), because "review my
changes" has more than one defensible answer in a 604-component catalogue.
An `expect` id that does not exist is reported as a data error — a stale eval is
worse than no eval.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import router

GOLDEN = Path(__file__).resolve().parent.parent / "evals" / "routing.jsonl"


def load_golden(path: Path | None = None) -> list[dict]:
    p = path or GOLDEN
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def ids(index: dict) -> set[str]:
    return {f"{d['kind']}:{d['id']}" for d in index["docs"]}


def run(index: dict, golden: list[dict] | None = None,
        project_context: list[str] | None = None, k: int = 5,
        rerank: bool = False, shortlist_k: int = 15,
        expand: bool = False, expand_kwargs: dict | None = None,
        semantic: bool = False, sections: bool = True) -> dict:
    if golden is None:  # `[]` means "no cases", not "use the default file".
        golden = load_golden()
    degraded = False
    known = ids(index)
    # An indexed directory names a document `kind:id`, and the id is already the
    # full relative path — so the qualified form reads `projets:projets/vpn`.
    # Accepting the bare path too is one line and removes a papercut that would
    # otherwise land in every evaluation file a user writes by hand.
    bare = {d["id"]: f"{d['kind']}:{d['id']}" for d in index["docs"]}
    rows, data_errors = [], []
    for case in golden:
        expect = [bare.get(e, e) for e in case["expect"]]
        missing = [e for e in expect if e not in known]
        if missing:
            data_errors.append({"q": case["q"], "missing": missing})
        expect = [e for e in expect if e in known]
        if not expect:
            continue
        pool = max(k, shortlist_k, 30) if rerank else k
        tw = None
        added = 0
        if expand:
            from . import expand as ex
            e = ex.build_terms(index, case["q"], **(expand_kwargs or {}))
            tw = e["weights"]
            # Counted, not assumed. `--expand` with a cold judgement cache or a
            # query whose seeds disagree adds nothing, and the run was then
            # presented as an expanded run with no way to tell otherwise.
            added = len(e["added"])
        if semantic:
            from . import semantic as sem
            if not sem.available():
                # Degrade, do not crash. `eccx recall` already falls back to the
                # lexical router when fastembed is absent; the evaluator used to
                # raise ModuleNotFoundError instead — so on a lean install the
                # *measurement* tool was the one thing that did not work, and it
                # died on a machine where the product itself was fine.
                semantic = False
                degraded = True
        if semantic:
            from . import semantic as sem
            # `load_all`, not `load_vectors`: the shipped router scores a
            # component by its best section, and an evaluator that only loads
            # document vectors measures a model nobody runs. This exact defect
            # (harness measuring something other than the product) already cost
            # a `--k` that never varied anything; TestEvaluatorUsesTheShipped-
            # Scorer locks it.
            allv = sem.load_all(index["docs"])
            D = None if allv is None else allv["docs"]
            qv = sem.embed_query(case["q"]) if D is not None else None
            results = router.score_hybrid(
                index, case["q"], top=pool,
                vector_matrix=D, query_vector=qv,
                section_matrix=(None if allv is None or not sections
                                else allv["sections"]),
                section_span=(None if allv is None or not sections
                              else allv["span"]),
                project_context=project_context, term_weights=tw)
        else:
            results = router.score(index, case["q"], top=pool,
                                   project_context=project_context,
                                   term_weights=tw)
        used_rerank = False
        escalated = False   # defined for every branch, not only `rerank`
        judged_deeper = False
        if rerank:
            from . import rerank as rr
            # `term_weights` must reach the pool, or `--expand --rerank`
            # silently ignores `--expand`: the weights were computed and
            # thrown away, and the run was byte-identical to `--rerank` alone.
            results, meta = rr.resolve(index, case["q"], k=shortlist_k,
                                       escalate_to=30, deep_to=50,
                                       ctx=project_context,
                                       term_weights=tw)
            used_rerank = meta["status"] != "lexical"
            escalated = meta.get("escalated", False)
            judged_deeper = meta.get("judged_deeper", False)
        ranked = [f"{r['doc']['kind']}:{r['doc']['id']}" for r in results][:k]
        rank = next((i + 1 for i, rid in enumerate(ranked) if rid in expect), None)
        rows.append({"q": case["q"], "expect": expect, "ranked": ranked,
                     "rank": rank, "reranked": used_rerank,
                     "escalated": escalated, "judged_deeper": judged_deeper,
                     "expanded": bool(added), "terms_added": added})

    n = len(rows) or 1
    metrics = {"cases": len(rows), "semantic": not degraded and semantic}
    # Always report 1/3/5 plus whatever depth was asked for. Building only
    # `recall@k` meant `eccx eval --k 3` produced no `recall@5` key and
    # `report()` crashed with KeyError on a perfectly valid run — a metric
    # function that only works at its default argument.
    # 10 and 20 are not vanity depths: they are the operating points of an
    # agent-in-the-loop product. Measured on 165 held-out queries:
    #     @1 27.3 %   @3 47.9 %   @10 64.8 %   @20 75.8 %   @50 84.2 %
    # A shortlist of 20 costs 677 tokens; reading the catalogue costs 1 071 212.
    # The router is a *candidate generator*, and its accuracy must be reported at
    # the depth a caller can afford, not only at top-1.
    for depth in sorted({1, 3, 5, 10, 20, k}):
        metrics[f"recall@{depth}"] = round(
            sum(1 for r in rows if r["rank"] and r["rank"] <= depth) / n, 3)
    metrics["mrr"] = round(sum(1 / r["rank"] for r in rows if r["rank"]) / n, 3)
    if expand:
        # Two numbers, because they answer different questions: how often the
        # run actually expanded, and how much it added when it did.
        metrics["expand_applied"] = round(
            sum(1 for r in rows if r["expanded"]) / n, 3)
        metrics["terms_added"] = round(
            sum(r["terms_added"] for r in rows) / n, 3)
    if rerank:
        metrics["rerank_coverage"] = round(
            sum(1 for r in rows if r["reranked"]) / n, 3)
        metrics["escalated"] = round(
            sum(1 for r in rows if r.get("escalated")) / n, 3)
        # Escalation that found nothing is not escalation worth the name.
        metrics["judged_deeper"] = round(
            sum(1 for r in rows if r.get("judged_deeper")) / n, 3)
    return {"metrics": metrics, "rows": rows, "data_errors": data_errors}


def report(result: dict, verbose: bool = True) -> str:
    lines = []
    m = result["metrics"]
    lines.append(f"golden set: {m['cases']} intents")
    lines.append(f"  recall@1  {m['recall@1']:.1%}")
    lines.append(f"  recall@3  {m['recall@3']:.1%}")
    lines.append(f"  recall@5  {m['recall@5']:.1%}")
    lines.append(f"  MRR       {m['mrr']:.3f}")
    failures = [r for r in result["rows"] if not r["rank"]]
    if "expand_applied" in m:
        lines.append(f"  expand    {m['expand_applied']:.1%} of queries "
                     f"({m['terms_added']:.1f} terms added)")
    if verbose and failures:
        lines.append(f"\nfailures ({len(failures)}):")
        for r in failures:
            lines.append(f"  Q: {r['q']}")
            lines.append(f"     expected one of: {', '.join(r['expect'])}")
            lines.append(f"     got: {', '.join(r['ranked'][:3]) or '(nothing)'}")
    weak = [r for r in result["rows"] if r["rank"] and r["rank"] > 1]
    if verbose and weak:
        lines.append(f"\nranked but not first ({len(weak)}):")
        for r in weak[:10]:
            lines.append(f"  #{r['rank']} {r['q']}  ->  {r['ranked'][0]}")
    if result["data_errors"]:
        lines.append("\nstale golden entries (id not in catalogue):")
        for d in result["data_errors"]:
            lines.append(f"  {d['q']}: {', '.join(d['missing'])}")
    return "\n".join(lines)
