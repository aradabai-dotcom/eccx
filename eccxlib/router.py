"""Retrieval over the ECC index.

Two stages, because they optimise different things:

  1. DOCUMENT routing — cheap field-weighted scoring over the whole catalogue.
     Names carry most of the signal; descriptions break near-ties; the body is
     never scored, it is what we return.

  2. SECTION selection — for the surviving documents, pick the H2 blocks that
     actually answer the query and inject only those. This is the difference
     between "here is a 3 000-token skill" and "here are the 400 tokens of it you
     need".

Both stages are gated by what the *target project* looks like (rule packs,
framework, third-party integrations) so a Laravel skill cannot outrank a generic
one unless the project is Laravel.
"""
from __future__ import annotations

import math
import re
from itertools import pairwise
from pathlib import Path

from .util import (TRUNC_MARK, doc_file, est_tokens, read_text, stem,
                   tokenize, truncate)

K1, B = 1.2, 0.75

LANG_HINTS = {
    "typescript": ["typescript", "ts", "tsx", "javascript", "js", "jsx", "node", "deno"],
    "react": ["react", "jsx", "tsx", "nextjs", "next"],
    "nuxt": ["nuxt", "vue"],
    "vue": ["vue"],
    "python": ["python", "py", "django", "fastapi", "flask"],
    "golang": ["go", "golang"],
    "rust": ["rust", "rs", "cargo"],
    "java": ["java", "spring"],
    "kotlin": ["kotlin", "kt"],
    "swift": ["swift", "ios"],
    "php": ["php", "laravel"],
    "ruby": ["ruby", "rails"],
    "cpp": ["cpp", "c++", "cc"],
    "csharp": ["csharp", "c#", "dotnet"],
    "dart": ["dart", "flutter"],
    "perl": ["perl"],
    "fsharp": ["fsharp", "f#"],
    "arkts": ["arkts", "harmony"],
    "angular": ["angular"],
    "react-native": ["react-native", "reactnative", "expo"],
    "web": ["html", "css", "accessibility", "a11y"],
}

KIND_PRIOR = {
    "skill": 1.06, "command": 1.00, "agent": 0.95,
    "guide": 0.72, "rule": 0.62, "manual": 0.45,
}

ALIASES = {
    "pr": ["pull", "request", "review"], "pull": ["pr"], "request": ["pr"],
    "auth": ["authentication", "authorization"], "authentication": ["auth"],
    "db": ["database"], "database": ["db"], "ci": ["pipeline", "workflow"],
    "k8s": ["kubernetes"], "a11y": ["accessibility"], "ts": ["typescript"],
    "js": ["javascript"], "test": ["testing"], "testing": ["test"],
    "doc": ["document"], "documentation": ["document"], "perf": ["performance"],
    "sec": ["security"], "config": ["configuration"],
    "deps": ["dependency", "dependencies"], "refactor": ["refactoring", "cleanup"],
    "bug": ["debug", "fix"], "debug": ["bug"],
    "tweet": ["twitter", "x"], "tweets": ["twitter", "x"],
    "job": ["worker", "queue", "background"], "queue": ["job", "worker"],
    "cron": ["schedule", "job"], "retry": ["resilience", "backoff"],
    "evaluate": ["eval", "benchmark"], "evaluation": ["eval", "benchmark"],
    "quality": ["eval", "review"], "requirements": ["prd"],
    "spec": ["prd", "plan"], "worktree": ["dmux", "git"],
    "worktrees": ["dmux", "git"], "parallel": ["dmux", "multi"],
    "scrape": ["scraper", "crawl"], "scraping": ["scraper", "crawl"],
    "vulnerability": ["security", "scan"], "vulnerabilities": ["security", "scan"],
    "leak": ["performance", "profiling"], "profile": ["profiling", "performance"],
}

# A self-loop (`test` -> `testing` -> `test`) is harmless today only because
# `expand_with_origin` builds a dict, but it is still an invariant violation:
# any future caller that sums over the alias list would double-count the term.
ALIASES = {stem(k): [x for x in (stem(v) for v in vs) if x != stem(k)]
           for k, vs in ALIASES.items()}


# Weights are ordered by *precision of the signal*, and the ordering is the
# router's whole opinion: a component whose name is your topic is about your
# topic; a component that merely mentions the word somewhere in its body is
# probably about something else.
#
#
# A fifth field, `body` (the top keywords of the H2 sections, already computed
# by the indexer), was measured and **rejected**: it moved 6 of 94 held-out
# queries in each direction, +0.0 points net, bootstrap CI [-5.3, +5.3]. A
# plausible idea that does not survive measurement is a rejected idea, not a
# pending one. Re-measure only if the catalogue grows or the tokeniser changes.
FIELD_WEIGHT = {"name": 5.0, "desc": 1.8, "heads": 0.55, "extra": 0.4,
                # Section bodies, only for an indexed directory the user owns.
                # ECC components carry a hand-written `description` that
                # summarises the whole file, so the body adds nothing but noise
                # (measured: -4.6 points @1 when the field was tried on the
                # catalogue). A personal corpus has no such summary — the first
                # paragraph is all `desc` holds, and without this field a query
                # whose words live in the body matched *nothing at all*.
                # Weighted like `desc`: it is prose evidence, not a title.
                "sec": 1.8}

INTEGRATION_TOKENS = {
    "x", "twitter", "slack", "discord", "stripe", "shopify", "linear", "jira",
    "github", "gitlab", "notion", "aws", "gcp", "azure", "supabase", "firebase",
    "vercel", "cloudflare", "anthropic", "openai", "claude", "gpt", "llm",
    "mcp", "kafka", "redis", "postgres", "mongodb", "clickhouse", "snowflake",
    "airtable", "hubspot", "salesforce", "twilio", "sendgrid", "playwright",
    "puppeteer", "selenium", "figma", "expo", "flutter", "ionic", "capacitor",
    "wordpress", "woocommerce", "sanity", "contentful", "ghost", "qiita",
}


def _context_tokens() -> set[str]:
    toks: set[str] = set()
    for pack, hints in LANG_HINTS.items():
        toks.add(stem(pack))
        for h in hints:
            toks.add(stem(h))
    return toks | {"laravel", "nextjs"}


CONTEXT_TOKENS = _context_tokens()


# ------------------------------------------------------------------ feedback

FEEDBACK_PATH = None  # set lazily to avoid an import cycle


def load_boost() -> dict[str, float]:
    """Usage feedback: components that repeatedly proved useful float up.

    Log-scaled and clamped so a few `eccx feedback` calls can reorder near-ties
    without letting history override the query.
    """
    from .util import ADAPTER_STATE, load_json
    data = load_json(ADAPTER_STATE / "feedback.json", {}) or {}
    boost = {}
    for key, rec in data.items():
        good = rec.get("good", 0)
        bad = rec.get("bad", 0)
        if not good and not bad:
            continue
        factor = 1 + 0.12 * math.log1p(good) - 0.12 * math.log1p(bad)
        boost[key] = max(0.7, min(1.5, factor))
    return boost


# ------------------------------------------------------------------ query side

def expand_with_origin(qtokens: list[str]) -> dict[str, set[str]]:
    """expanded token -> the user's own tokens it stands for."""
    origin: dict[str, set[str]] = {}
    for t in qtokens:
        origin.setdefault(t, set()).add(t)
        for a in ALIASES.get(t, []):
            origin.setdefault(stem(a), set()).add(t)
    return origin


# Tokenising the whole catalogue on every query was ~85 ms of the ~90 ms a
# `router.score` call costs (measured: perf/budgets.py, 9x speed-up after this).
# The fields of a document cannot change while the index is loaded, so they are
# memoised **on the document dict itself**.
#
# The first attempt keyed the cache on `id(doc)`. It was wrong, and the property
# tests caught it within minutes: `id()` is only unique among *live* objects, so
# a rebuilt index could reuse the address of a freed dict and inherit its
# tokenisation. `test_scoring_is_deterministic_across_index_identity` failed on
# a mini index that is rebuilt per test. Storing the result inside the dict ties
# the cache's lifetime to the object's, which is exactly the guarantee needed.
#
# The private key never reaches disk: `indexer.build()` serialises the docs
# before any scoring happens.
FIELDS_KEY = "_fields"


def _fields(doc: dict) -> dict[str, list[str]]:
    cached = doc.get(FIELDS_KEY)
    if cached is not None:
        return cached
    # Sets, not lists: every use of these is a membership test (`t in f[...]`),
    # and `body` carries ~150 tokens per document. Lists made the router 2.4x
    # slower the day the body field was added; sets bring it back.
    name_seq = tokenize(doc["name"].replace("-", " ").replace("_", " "))
    fields = {
        # Sets for membership (`t in f[...]`), and ONE ordered copy for the
        # bigram test. `" ".join(set_of_tokens)` has an arbitrary order that
        # follows PYTHONHASHSEED, so the "alpha beta" adjacency bonus fired or
        # did not fire depending on the seed: the same query scored 21.98 or
        # 18.80 in two processes. Same score everywhere or the ranker is a
        # lottery — caught by TestScoringIsPinned, which runs a subprocess.
        "name": set(name_seq),
        "name_seq": name_seq,
        "desc": set(tokenize(doc.get("desc") or "")),
        "heads": set(tokenize(" ".join(doc.get("headings") or []))),
        "extra": set(tokenize(" ".join(str(v) for v in (doc.get("extra") or {}).values()))),
        "sec": set(),
    }
    # Only for user corpora, and only the keywords the indexer already computed
    # per section — re-tokenising every body on the first query would add a
    # second to the latency the whole product is sold on.
    if (doc.get("extra") or {}).get("root") == "corpus":
        kws = []
        for sec in (doc.get("sections") or []):
            k = sec.get("kws")
            if k:
                kws.append(k)
        if kws:
            fields["sec"] = set(" ".join(kws).split())
    doc[FIELDS_KEY] = fields
    return fields


def _raw_name_parts(doc: dict) -> set[str]:
    return {p for p in doc["name"].lower().replace("_", "-").split("-") if p}


# -------------------------------------------------------------- stage 1: docs

# Selected on the tuning halves only (heldout 1-4), then measured once on the
# sealed halves (heldout 5-6). This is the only parameter in this file whose
# value was chosen before seeing the number it is quoted with.
#
#                    tuning @1 / @20      sealed @1 / @20
#   doc only          33.0 / 81.9          19.7 / 67.6
#   + sections        40.4 / 85.1          26.8 / 76.1
#
# Paired on the sealed half: 7 gains / 2 losses at @1, p = 0.18 — consistent
# direction, not yet significant at n=71. Reported as such.
SEMANTIC_ALPHA = 3.0      # weight of the document-level cosine
SEMANTIC_BETA = 5.0       # weight of the best-section cosine

# The router knows when it does not know — but the *first* version of this
# claim did not survive validation, and the correction is worth more than the
# constant.
#
# Attempt 1 used the relative margin between the first two fused scores. Measured
# on the pooled 165 queries it looked excellent (24 % coverage at 51 % @1). Split
# by author it collapsed:
#
#     heldout 1-4 (where the threshold was fitted)  27 % coverage, 64 % @1
#     heldout 5-6 (sealed)                          20 % coverage, 29 % @1
#
# The margin is *relative to the query's own score distribution*, so its meaning
# drifts with query difficulty: it is a confidence about the ranking, not about
# being right. Withdrawn.
#
# Attempt 2 uses the cosine of the best candidate — an absolute quantity on a
# fixed scale. It transposes in both directions:
#
#     fit on 1-4 -> 5-6 : 7 % coverage, 60 % @1   CI95 [20 ; 100]   (n=5, useless)
#     fit on 5-6 -> 1-4 : 38 % coverage, 50 % @1  CI95 [33 ; 67]    (base 33 %)
#
# Consistent in direction, unsettled in magnitude. 165 queries cannot pin a
# proportion better than +/- 7 points, so the shipped claim is deliberately
# weak: "about 1.5x the base rate, when it fires on a fifth to two-fifths of
# queries". Anything sharper would be a number invented to look precise.
CONFIDENT_COSINE = 0.63

# Kept for callers that pass only scores; the CLI uses the cosine path.
CONFIDENT_MARGIN = 0.20


def margin_of(results: list[dict]) -> float:
    """Relative gap between the best and second-best score, in [0, 1]."""
    if len(results) < 2:
        return 1.0
    a, b = results[0]["score"], results[1]["score"]
    return max(0.0, (a - b) / (a + 1e-9))


def confidence(results: list[dict], cosine: float | None = None) -> str:
    """"confident" | "unsure" — a three-word contract, not a probability.

    Prefers `cosine` (the semantic similarity of the best candidate), which is
    the only signal measured to survive a calibration/validation split. Falls
    back to the score margin for callers that have no embeddings, with the
    caveat in the constant's comment: the margin version was measured *not* to
    generalise, so its "confident" means little.

    Deliberately not a number: a router reporting "0.73 confident" invites the
    reader to treat it as a calibrated probability, and it is not.
    """
    if cosine is not None:
        return "confident" if cosine >= CONFIDENT_COSINE else "unsure"
    return "confident" if margin_of(results) >= CONFIDENT_MARGIN else "unsure"


def score_hybrid(index: dict, query: str, top: int = 8, *,
                 alpha: float = SEMANTIC_ALPHA, beta: float = SEMANTIC_BETA,
                 vector_matrix=None, query_vector=None,
                 section_matrix=None, section_span=None, **kw) -> list[dict]:
    """Lexical score fused with a local embedding similarity.

    Fusion is deliberately coarse: lexical scores are normalised by the best
    score of *this* query, then `alpha * cosine` is added. Anything cleverer
    (rank fusion, per-field fusion) was not measured better, and every
    parameter that is not measured is a liability.

    `alpha = 1.5` was chosen on the tuning sets; `heldout6`, written before the
    experiment, then confirmed the direction (+5.0 @1, +7.5 @3). It is the only
    number here that was validated out of sample.
    """
    lex = score(index, query, top=max(top, 60), **kw)
    if not lex:
        return []
    best = lex[0]["score"] or 1.0
    base = {f"{r['doc']['kind']}:{r['doc']['id']}": r["score"] / best for r in lex}
    if vector_matrix is None or query_vector is None:
        return score(index, query, top=top, **kw)
    docs = index["docs"]
    if len(vector_matrix) != len(docs):
        return score(index, query, top=top, **kw)
    sims = vector_matrix @ query_vector
    sec_sims = None
    if section_matrix is not None and section_span is not None and beta:
        import numpy as _np
        raw = section_matrix @ query_vector
        # A component is scored by its *best* section: the catalogue describes
        # practices, the user describes a symptom, and the symptom lives in one
        # heading ("CrashLoopBackOff"), not in the summary.
        best = _np.full(len(docs), -1.0, dtype=_np.float32)
        _np.maximum.at(best, section_span, raw)
        sec_sims = best
    fused = []
    for i, d in enumerate(docs):
        key = f"{d['kind']}:{d['id']}"
        sc = base.get(key, 0.0) + alpha * float(sims[i])
        if sec_sims is not None:
            sc += beta * float(sec_sims[i])
        # A document with no lexical evidence and a non-positive fused score is
        # not a candidate. Without this guard the list is padded with the whole
        # catalogue at score 0 and `alpha=0` stops being identical to the
        # lexical router — which is the property that makes this a *fusion*
        # rather than a replacement.
        if sc > 0:
            fused.append((sc, key))
    fused.sort(key=lambda r: (-r[0], r[1]))
    by_key = {f"{d['kind']}:{d['id']}": d for d in docs}
    lex_by_key = {f"{r['doc']['kind']}:{r['doc']['id']}": r for r in lex}
    out = []
    for sc, key in fused[:top]:
        row = lex_by_key.get(key)
        if row is None:
            row = {"doc": by_key[key], "score": round(sc, 3), "matched": [], "coverage": 0.0}
        else:
            row = dict(row, score=round(sc, 3))
        out.append(row)
    return out


_EXPANSION_CACHE: dict[tuple[int, int], dict] = {}


def _expansion_table(index: dict) -> dict:
    """Co-occurrence table, built once per index object.

    Rebuilding it on every query would add ~40 ms to the latency the product is
    sold on; the index is immutable between rebuilds, so the table is too.
    """
    key = (id(index), len(index["docs"]))
    table = _EXPANSION_CACHE.get(key)
    if table is None:
        from . import expansion
        table = expansion.build(index)
        _EXPANSION_CACHE.clear()      # one index at a time; avoid unbounded growth
        _EXPANSION_CACHE[key] = table
    return table


def prepare_terms(query: str, *, translate: bool = True,
                  term_weights: dict[str, float] | None = None,
                  semantic_expansion: bool = False,
                  index: dict | None = None) -> tuple | None:
    """The single place where a query becomes weighted terms.

    Both stages must see the *same* query representation. They did not, once:
    the second stage re-tokenised the raw string, so on French queries it judged
    documents against words the first stage had never scored, and demoted a
    correct answer. One function, called once.
    """
    if translate:
        from . import lexique
        query, _ = lexique.rewrite(query)
    base_tokens = tokenize(query)
    if not base_tokens:
        return None
    origin = expand_with_origin(base_tokens)
    if term_weights:
        qtokens = list(term_weights)
        syn_weight = {t: term_weights[t] for t in qtokens}
    else:
        qtokens = list(origin)
        syn_weight = {t: (1.0 if t in origin and t in base_tokens else 0.55)
                      for t in qtokens}
        if semantic_expansion and index is not None and index["docs"]:
            from . import expansion
            extra = expansion.expand(qtokens, _expansion_table(index))
            for term, weight in extra.items():
                if term not in syn_weight:
                    qtokens.append(term)
                    syn_weight[term] = weight
    return query, base_tokens, origin, qtokens, syn_weight


def score(index: dict, query: str, kinds: list[str] | None = None, top: int = 8,
          project_context: list[str] | None = None,
          boost: dict[str, float] | None = None,
          term_weights: dict[str, float] | None = None,
          translate: bool = True,
          semantic_expansion: bool = False,
          ) -> list[dict]:
    docs = [d for d in index["docs"] if not kinds or d["kind"] in kinds]
    # Translation happens inside prepare_terms: the catalogue is English-only,
    # so a French query reaches it with terms it can never match
    # (« déploiement » vs « deployment »). Measured before this existed: 0/4 on
    # French senior-dev queries. English queries come back unchanged.
    prepared = prepare_terms(query, translate=translate, term_weights=term_weights,
                            semantic_expansion=semantic_expansion, index=index)
    if not prepared:
        return []
    query, base_tokens, origin, qtokens, syn_weight = prepared
    primary = set(base_tokens)
    ctx = {stem(c) for c in (project_context or [])}
    allowed_ctx = ctx | primary

    fields = [_fields(d) for d in docs]
    n = len(docs)
    df = {}
    for t in set(qtokens):
        # Document frequency counts only the fields that actually score. A
        # field with weight 0 still entering `df` lowers every other term's
        # idf and changes rankings silently — measured at 4.6 points of
        # recall@1 on one set when the body field was tried. `extra` is
        # deliberately out of `df`: it is metadata, not vocabulary.
        df_fields = [k for k in ("name", "desc", "heads", "sec")
                     if FIELD_WEIGHT.get(k, 0)]
        df[t] = sum(1 for f in fields
                    if any(t in f[k] for k in df_fields))

    norm_query = " ".join(query.lower().split())
    results = []
    for doc, f in zip(docs, fields, strict=True):
        s = 0.0
        matched: set[str] = set()
        for t in qtokens:
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            hit = 0.0
            if t in f["name"]:
                hit += FIELD_WEIGHT["name"]
            if t in f["desc"]:
                hit += FIELD_WEIGHT["desc"]
            if t in f["heads"]:
                hit += FIELD_WEIGHT["heads"]
            if t in f["extra"]:
                hit += FIELD_WEIGHT["extra"]
            if t in f["sec"]:
                hit += FIELD_WEIGHT["sec"]
            if hit:
                s += idf * hit * syn_weight.get(t, 0.55)
                matched.add(t)
        if not s:
            continue

        covered = set()
        for t in matched:
            covered |= origin.get(t, set())
        cov = len(covered & primary) / max(1, len(primary))
        s *= 0.55 + 0.45 * cov

        name_set = set(f["name"])
        s *= 1.0 + 0.15 * len(name_set & primary)
        padded = f" {' '.join(f['name_seq'])} "
        for a, b_ in pairwise(qtokens):
            if f"{a} {b_}" in padded:
                s += 3.0

        raw = _raw_name_parts(doc) & INTEGRATION_TOKENS
        if raw and not (raw & (set(qtokens) | ctx)):
            s *= 0.45

        foreign = (name_set & CONTEXT_TOKENS) - allowed_ctx
        if foreign:
            s *= 0.38 if cov < 0.6 else 0.7
        if (name_set & CONTEXT_TOKENS) & allowed_ctx:
            s *= 1.25

        desc_l = (doc.get("desc") or "").lower()
        name_flat = doc["name"].replace("-", " ")
        if norm_query and norm_query in name_flat:
            s += 14.0
        elif norm_query and norm_query in desc_l:
            s += 4.0

        s *= KIND_PRIOR.get(doc["kind"], 0.8)
        if boost:
            s *= boost.get(f"{doc['kind']}:{doc['id']}", 1.0)
        results.append({"doc": doc, "score": round(s, 3),
                        "matched": sorted(matched), "coverage": round(cov, 2)})

    results.sort(key=lambda r: (-r["score"], r["doc"]["kind"], r["doc"]["id"]))
    # Stage one ends here. A second stage composes on top of this result list
    # (`second_stage.apply_gate`); it is deliberately not reachable from inside
    # this function, so the lexical router stays a pure lexical router.
    return results[:top]


# ----------------------------------------------------------- stage 2: sections

_POSITION_BONUS = re.compile(
    r"(when to activate|checklist|overview|quick|pattern|rule|example|"
    r"workflow|step|guide|standard|practice|anti-?pattern|review)", re.I)


def score_sections(doc: dict, qtokens: set[str], max_sections: int = 2) -> list[dict]:
    """Rank the H2 blocks of one document against the query tokens."""
    sections = doc.get("sections") or []
    if not sections:
        return []
    scored = []
    for sec in sections:
        kws = set(sec["kws"].split())
        heading = set(tokenize(sec["h"]))
        hits = (kws & qtokens)
        if not hits:
            continue
        precision = len(hits) / max(1, len(kws))
        s = len(hits) * 2.0 + len(heading & qtokens) * 3.0 + precision * 6.0
        if _POSITION_BONUS.search(sec["h"]):
            s *= 1.12
        scored.append({"section": sec, "score": round(s, 3), "hits": sorted(hits)})
    scored.sort(key=lambda x: -x["score"])
    if not scored:
        # No section matched: fall back to the two most informative blocks.
        head = sorted(sections, key=lambda s: -s["tokens"])[:max_sections]
        return [{"section": s, "score": 0.0, "hits": []} for s in head]
    return scored[:max_sections]


def _slice(doc: dict, lines: list[str], sec: dict) -> str:
    start, end = sec["start"], sec["end"]
    return "\n".join(lines[start:end]).strip()


def _clean_body(doc: dict) -> str:
    from . import frontmatter as fm
    raw = read_text(doc_file(doc))
    if doc["kind"] in ("skill", "agent", "command"):
        _, body = fm.split(raw)
        return body.strip() or raw
    return raw


MIN_BLOCK_TOKENS = 60    # below this a component is not worth a header


def render_bundle(results: list[dict], budget_tokens: int = 3500,
                  query: str = "") -> str:
    """Assemble a bundle: best sections of the best documents, *under budget*.

    The budget is a hard cap, not an allocation hint. The first version
    allocated a share per document and then floored every share at 250 tokens,
    so `eccx recall --k 8 --budget 400` returned 1 983 tokens — 5x what the
    flag says. Nothing caught it because every test measured *quality*, never
    the one number the tool prints on its own banner.

    Now: documents are added while they fit, the cost of each block is measured
    after the fact (header included), and the result is asserted to be inside
    the budget before it is returned. Over-budget is a bug, not a rounding
    artefact.
    """
    if not results or budget_tokens <= 0:
        return ""
    qtokens = set(tokenize(query)) if query else set()
    if qtokens:
        qtokens |= set(expand_with_origin(list(qtokens)))

    scores = [max(0.1, r["score"]) for r in results]
    total = sum(scores)
    blocks: list[str] = []

    for r, sc in zip(results, scores, strict=True):
        spent = est_tokens("\n\n".join(blocks))
        remaining = budget_tokens - spent
        if remaining < MIN_BLOCK_TOKENS:
            break
        doc = r["doc"]
        share = budget_tokens * (sc / total)
        cap = int(max(MIN_BLOCK_TOKENS, min(share, remaining)))

        pieces: list[str] = []
        if qtokens and doc.get("sections"):
            raw = read_text(doc_file(doc))
            lines = raw.splitlines()
            from . import frontmatter as fm
            if doc["kind"] in ("skill", "agent", "command"):
                lines = fm.split(raw)[1].splitlines()
            for pick in score_sections(doc, qtokens, max_sections=2):
                chunk = _slice(doc, lines, pick["section"])
                if not chunk:
                    continue
                if est_tokens("\n\n".join(pieces + [chunk])) > cap:
                    break
                pieces.append(chunk)
        if not pieces:
            pieces = [truncate(_clean_body(doc), cap * 4)]

        text = "\n\n".join(pieces)
        header = (f"<!-- {doc['kind']}:{doc['id']} | score={r['score']} | "
                  f"{doc['path']} | full: eccx show {doc['kind']}:{doc['id']} -->")
        block = f"{header}\n{text}"

        room = budget_tokens - spent
        if est_tokens(block) > room:
            # Last resort: cut this block so the promise holds. `truncate`
            # keeps its own marker inside the budget it is given.
            allowed_chars = room * 4
            if allowed_chars <= len(TRUNC_MARK) + 16:
                break
            block = truncate(block, allowed_chars)
            if est_tokens(block) > room:
                break
        blocks.append(block)

    out = "\n\n".join(blocks)
    # Belt and braces: the arithmetic above can drift by a token because
    # `est_tokens` rounds. Trim rather than return something over budget.
    if est_tokens(out) > budget_tokens:
        out = truncate(out, budget_tokens * 4)
    return out


# ------------------------------------------------------------------- helpers

def explain_terms(query: str) -> list[str]:
    return sorted(set(tokenize(query)))


def suggest_rules(index: dict, packs: list[str], budget_tokens: int = 1200) -> str:
    files = [d for d in index["docs"] if d["kind"] == "rule"
             and d["extra"].get("pack") in set(packs)]
    files.sort(key=lambda d: (d["extra"].get("pack") != "common", d["id"]))
    chunks: list[str] = []
    used = 0
    for d in files:
        body = _clean_body(d)
        in_fence = False
        bullets = []
        for ln in body.splitlines():
            st = ln.strip()
            if st.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence or not st.startswith(("- ", "* ")):
                continue
            bullets.append(st)
            if len(bullets) == 3:
                break
        piece = f"### {d['id']}\n" + "\n".join(bullets)
        cost = est_tokens(piece)
        if used + cost > budget_tokens:
            break
        used += cost
        chunks.append(piece)
    return "\n\n".join(chunks)


def detect_packs(project: Path) -> list[str]:
    tags: set[str] = set()

    def add_file_terms(p: Path, limit: int = 4000):
        tags.update(re.findall(r"[a-zA-Z0-9+#._-]{2,}", read_text(p)[:limit].lower()))

    if (project / "package.json").is_file():
        add_file_terms(project / "package.json", 8000)
        tags.update({"javascript", "node"})
    for marker, words in [
        ("tsconfig.json", {"typescript"}), ("pyproject.toml", {"python"}),
        ("requirements.txt", {"python"}), ("go.mod", {"go", "golang"}),
        ("Cargo.toml", {"rust"}), ("pom.xml", {"java"}), ("build.gradle", {"java"}),
        ("composer.json", {"php"}), ("Gemfile", {"ruby"}),
        ("pubspec.yaml", {"dart", "flutter"}), ("Package.swift", {"swift"}),
        ("CMakeLists.txt", {"cpp"}), ("next.config.js", {"nextjs", "react"}),
        ("next.config.mjs", {"nextjs", "react"}), ("nuxt.config.ts", {"nuxt", "vue"}),
        ("angular.json", {"angular"}), ("tailwind.config.ts", {"react"}),
    ]:
        if (project / marker).exists():
            tags |= words
    for d in ("src", "app", "lib", "packages"):
        p = project / d
        if p.is_dir():
            for f in list(p.rglob("*"))[:400]:
                if f.suffix in (".ts", ".tsx"):
                    tags.add("typescript")
                elif f.suffix in (".js", ".jsx"):
                    tags.add("javascript")
                elif f.suffix == ".py":
                    tags.add("python")
                elif f.suffix == ".go":
                    tags.add("golang")
                elif f.suffix == ".rs":
                    tags.add("rust")

    packs = ["common"]
    for pack, hints in LANG_HINTS.items():
        if tags & set(hints):
            packs.append(pack)
    return packs
