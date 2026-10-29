"""Property tests — universal claims, not anecdotes.

Why a separate file: these assert things that must hold for *every* input, so
they are written against generated inputs (seeded, deterministic) and against
the whole catalogue rather than one hand-picked query.

The distinction from the rest of the suite matters. `test_routing.py` says
"for this query, this component wins" — a fact about one data point, which can
break for reasons that are not bugs. Here we say "for any query, the top-k is a
prefix of the top-2k": a claim that cannot be true by luck, and whose violation
is always a defect.

Every property below is a claim the code has actually been wrong about at some
point, or a claim whose violation would be silent:

  * prefix property       — depth is a *view*, not a ranking parameter
  * permutation property  — a judgement reorders, it never invents candidates
  * no-resurrection       — the safety rule of the projection (§19 in QUALITY)
  * metric monotonicity   — adding a solved case cannot lower recall
  * index idempotence     — a rebuild must not renumber or duplicate
"""
from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eccxlib import evaluate, frontmatter as fm, indexer, rerank, router, util  # noqa: E402


def ids_of(results: list[dict]) -> list[str]:
    return [f"{r['doc']['kind']}:{r['doc']['id']}" for r in results]


# Queries built from the catalogue's own vocabulary, so they are realistic
# without having been written by the person who wrote the router.
def sample_queries(index: dict, n: int = 40, seed: int = 20261028) -> list[str]:
    rng = random.Random(seed)
    docs = index["docs"]
    out = []
    for _ in range(n):
        doc = rng.choice(docs)
        words = doc["id"].replace("-", " ").split()
        if doc.get("desc"):
            words += rng.sample(doc["desc"].split(), min(4, len(doc["desc"].split())))
        rng.shuffle(words)
        out.append(" ".join(words[:6]))
    return out


class TestRouterProperties(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = indexer.load()
        cls.queries = sample_queries(cls.idx)

    def test_top_k_is_a_prefix_of_top_2k(self):
        """Depth selects a view of one ranking; it must not change the ranking.

        If this fails, `eccx recall --k 4` and `eccx eval --shortlist 15` are
        answering different questions, and every metric measured at one depth
        is meaningless at another.
        """
        for q in self.queries:
            with self.subTest(q=q):
                shallow = ids_of(router.score(self.idx, q, top=5))
                deep = ids_of(router.score(self.idx, q, top=10))
                self.assertEqual(deep[: len(shallow)], shallow)

    def test_scores_are_sorted_and_positive(self):
        for q in self.queries:
            with self.subTest(q=q):
                scores = [r["score"] for r in router.score(self.idx, q, top=15)]
                self.assertTrue(scores, q)
                self.assertEqual(scores, sorted(scores, reverse=True))
                self.assertTrue(all(s > 0 for s in scores))

    def test_scoring_is_deterministic_across_index_identity(self):
        """Same content, different dict objects — same answer.

        Guards against accidental dependence on insertion order or on state
        left in a module-level cache by a previous query.
        """
        import copy
        clone = copy.deepcopy(self.idx)
        for q in self.queries[:15]:
            with self.subTest(q=q):
                a = router.score(self.idx, q, top=8)
                b = router.score(clone, q, top=8)
                self.assertEqual(ids_of(a), ids_of(b))
                self.assertEqual([r["score"] for r in a], [r["score"] for r in b])

    def test_kind_filter_is_a_filter_not_a_rerank(self):
        """`--kind skill` must answer "the best skills", not "the skills that
        happen to be in the global top 20".

        Note what this property does *not* claim: the order within the filtered
        set can differ, because IDF is recomputed on the filtered corpus (a
        term present in 3 of 314 skills is more discriminative than one present
        in 3 of 607 components). That is a deliberate design choice, so the
        invariant asserted here is containment — every filtered result exists
        in the catalogue with that kind, and the filtered set is not a truncation
        artefact. Claiming order-preservation would have been a test that fails
        for a reason that is not a bug.
        """
        catalogue = {f"{d['kind']}:{d['id']}" for d in self.idx["docs"]}
        for q in self.queries[:15]:
            with self.subTest(q=q):
                only_skill = ids_of(router.score(self.idx, q, kinds=["skill"], top=20))
                self.assertTrue(all(i.startswith("skill:") for i in only_skill))
                self.assertTrue(set(only_skill) <= catalogue)
                # and it really is "the best skills": all 20 slots filled
                n_skills = sum(1 for d in self.idx["docs"] if d["kind"] == "skill")
                self.assertEqual(len(only_skill), min(20, n_skills))

    def test_coverage_is_a_ratio(self):
        for q in self.queries[:15]:
            with self.subTest(q=q):
                for r in router.score(self.idx, q, top=10):
                    self.assertGreaterEqual(r["coverage"], 0.0)
                    self.assertLessEqual(r["coverage"], 1.0)

    def test_boosting_the_top_never_demotes_it(self):
        """Feedback is a nudge, not a coin flip: this is its whole contract."""
        for q in self.queries[:20]:
            with self.subTest(q=q):
                base = router.score(self.idx, q, top=5)
                if not base:
                    continue
                top_id = ids_of(base)[0]
                boosted = router.score(self.idx, q, top=5, boost={top_id: 2.0})
                self.assertEqual(ids_of(boosted)[0], top_id)
                self.assertGreater(boosted[0]["score"], base[0]["score"])

    def test_unknown_kinds_and_huge_k_are_safe(self):
        self.assertEqual(router.score(self.idx, "security review", kinds=["nope"]), [])
        self.assertLessEqual(len(router.score(self.idx, "security review", top=10_000)),
                             len(self.idx["docs"]))

    def test_tokenize_is_compositional(self):
        """A token present in A is present in "A B": no cross-word interference."""
        for q in self.queries[:20]:
            with self.subTest(q=q):
                alone = util.tokenize(q)
                joined = util.tokenize(q + " kubernetes")
                for t in set(alone):
                    self.assertIn(t, joined)


class TestRerankProperties(unittest.TestCase):
    """The trust rules, stated as invariants over random judgements."""

    @classmethod
    def setUpClass(cls):
        cls.idx = indexer.load()
        cls.queries = sample_queries(cls.idx, n=15, seed=7)

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self._real = rerank.CACHE
        rerank.CACHE = Path(self._tmp.name) / "cache.json"

    def tearDown(self):
        rerank.CACHE = self._real
        self._tmp.cleanup()

    def test_apply_order_returns_a_permutation(self):
        for q in self.queries:
            pool = rerank.shortlist(self.idx, q, k=10)
            if len(pool) < 3:
                continue
            ids = ids_of(pool)
            for order in ([ids[-1]], [ids[-1], ids[0]], list(reversed(ids))):
                with self.subTest(q=q, order=order[:2]):
                    rerank.apply_order(q, pool, order)
                    out = ids_of(rerank.shortlist(self.idx, q, k=10))
                    self.assertEqual(sorted(out), sorted(ids))
                    ordered, used = rerank.reranked_results(q, rerank.shortlist(self.idx, q, k=10))
                    self.assertTrue(used)
                    self.assertEqual(sorted(ids_of(ordered)), sorted(ids))

    def test_projection_never_resurrects_a_candidate(self):
        """A judgement may only reorder components that were candidates when
        it was made. This is the safety rule that makes projection acceptable
        at all — violate it and a stale judgement can summon a component that
        today's query has no reason to return."""
        rng = random.Random(11)
        for q in self.queries:
            pool = rerank.shortlist(self.idx, q, k=10)
            if len(pool) < 5:
                continue
            ids = ids_of(pool)
            picked = rng.sample(ids, 3)
            rerank.apply_order(q, pool, picked)
            # a *different* pool: overlap is high, but 3 ids are new
            wider = rerank.shortlist(self.idx, q, k=14)
            ordered, _rec, _exact = rerank._project(q, wider)
            if ordered is None:
                continue
            current = set(ids_of(wider))
            self.assertTrue(set(ids_of(ordered)) <= current,
                            "projection produced an id that was not a candidate")

    def test_resolve_is_bounded_by_the_deepest_pool(self):
        for q in self.queries[:8]:
            res, meta = rerank.resolve(self.idx, q, k=15, escalate_to=30, deep_to=50)
            with self.subTest(q=q):
                self.assertLessEqual(len(res), 50)
                self.assertIn(15, meta["steps"])
                self.assertEqual(meta["steps"], sorted(set(meta["steps"])))

    def test_a_full_coverage_judgement_short_circuits_the_cascade(self):
        for q in self.queries[:10]:
            pool = rerank.shortlist(self.idx, q, k=15)
            rerank.apply_order(q, pool, [ids_of(pool)[-1]])
            _, meta = rerank.resolve(self.idx, q, k=15)
            with self.subTest(q=q):
                self.assertEqual(meta["steps"], [15])
                self.assertEqual(meta["coverage"], 1.0)


class TestIndexAndMetricProperties(unittest.TestCase):
    def test_index_build_is_idempotent(self):
        """Two builds of the same source must produce the same catalogue.

        The index is a cache with a version; if a rebuild could renumber or
        duplicate, every cached judgement keyed on candidate ids would rot.
        """
        a = indexer.build()
        b = indexer.build()
        self.assertEqual([d["id"] for d in a["docs"]], [d["id"] for d in b["docs"]])
        self.assertEqual([d["kind"] for d in a["docs"]], [d["kind"] for d in b["docs"]])
        self.assertEqual([d.get("sections") for d in a["docs"]],
                         [d.get("sections") for d in b["docs"]])

    def test_no_duplicate_component_ids(self):
        idx = indexer.load()
        keys = [f"{d['kind']}:{d['id']}" for d in idx["docs"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_section_ranges_are_ordered_and_inside_the_body(self):
        for doc in indexer.load()["docs"]:
            body = None
            for sec in doc.get("sections") or []:
                self.assertLess(sec["start"], sec["end"], doc["id"])
                if body is None:
                    text = util.read_text(util.doc_file(doc))
                    _, body = fm.split(text) if doc["kind"] in ("skill", "agent", "command") else (None, text)
                    body = body.splitlines()
                with self.subTest(doc=doc["id"], section=sec["h"]):
                    self.assertLessEqual(sec["end"], len(body))

    def test_metrics_are_monotone_under_a_solved_case(self):
        """Adding a case the router already answers cannot lower recall@k.

        A metric where this fails is not a metric; it would let "we removed the
        easy cases" look like an improvement.
        """
        idx = indexer.load()
        base_cases = [{"q": "security review authentication",
                       "expect": ["skill:security-review"]}]
        extra = [{"q": "react performance", "expect": ["skill:react-performance"]}]
        base = evaluate.run(idx, base_cases, k=3)["metrics"]
        more = evaluate.run(idx, base_cases + extra, k=3)["metrics"]
        self.assertGreaterEqual(more["recall@1"], base["recall@1"])
        self.assertGreaterEqual(more["mrr"], base["mrr"])

    def test_empty_golden_never_falls_back_to_the_default_file(self):
        # The exact bug class that shipped once: `golden or load_golden()`.
        res = evaluate.run(indexer.load(), [])
        self.assertEqual(res["metrics"]["cases"], 0)
        self.assertEqual(res["rows"], [])

    def test_est_tokens_is_monotone_and_never_zero(self):
        for n in (0, 1, 10, 1000):
            with self.subTest(n=n):
                text = "x" * n
                self.assertGreaterEqual(util.est_tokens("x" * (n + 1)), util.est_tokens(text))
                self.assertGreaterEqual(util.est_tokens(text), 1)

    def test_truncate_is_idempotent_and_bounded(self):
        for n in (10, 100, 1000):
            with self.subTest(n=n):
                once = util.truncate("a" * 5000, n)
                self.assertLessEqual(len(once), n)
                self.assertEqual(util.truncate(once, n), once)


if __name__ == "__main__":
    unittest.main()
