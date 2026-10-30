"""Performance budgets — deliberately NOT part of the unit suite.

Why separate:

  * A unit test asserts behaviour; a timing assertion asserts *the machine*.
    Mixing them is how a suite becomes flaky: the 5 s index-build test turned
    the whole gate red the moment it ran under coverage instrumentation (§24).
  * The unit suite runs 259 tests in a few minutes and must stay deterministic.
    This file runs 8 measurements and must stay *repeatable on this sandbox*,
    which is a weaker promise — and it says so.

Usage:
    python3 perf/budgets.py            # measure, compare, exit 1 if over
    python3 perf/budgets.py --json     # machine-readable
    python3 perf/budgets.py --update   # print budgets to paste back below

Each budget follows one declared rule, not a number typed by hand:

    budget = max(3 x median, 1.5 x p90, floor)

`floor` is 0.05 s, because below ~5 ms the timer/scheduler granularity of this
sandbox is the same order as the measurement and a 3x budget would be inside the
noise. The rule is enforced by `--update`, which *prints* the table; a budget
that was hand-inflated to 30x medians (the first version of this file was) can
never trip on a real regression, which makes it decoration.

Never run under `coverage` — tracing multiplies timings by 2-3x, which is
exactly the mistake §24 documents.
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eccxlib import evaluate, indexer, rerank, router  # noqa: E402
from eccxlib.util import ECC_ROOT  # noqa: E402

UPSTREAM = "https://github.com/affaan-m/ECC"

REPEATS = 5
FLOOR_S = 0.05          # below this, the sandbox's scheduler dominates
BUDGET_FACTOR = 3.0     # a real regression is ~an order of magnitude, not 3x
P90_FACTOR = 1.5


def declared_budget(median: float, p90: float) -> float:
    """The one rule, in one place. See the module docstring."""
    return round(max(BUDGET_FACTOR * median, P90_FACTOR * p90, FLOOR_S), 2)


def sample(fn, repeats: int = REPEATS) -> dict:
    """Median and p90 of N runs, after one warm-up.

    Median, not mean: one scheduling hiccup on a shared 2-vCPU box must not
    decide the verdict. p90 is kept because a budget that ignores spread is a
    budget that flakes; the CV is printed so the reader can see it.

    Honesty about the statistic: with REPEATS=5 the "p90" is the largest of five
    samples (index round(0.9 * 4) = 4). It is a spread guard, not a real
    percentile. It is still the right guard here — the budget must survive the
    slowest run of a short sample.
    """
    fn()
    samples = []
    for _ in range(repeats):
        t = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t)
    ordered = sorted(samples)
    median = statistics.median(samples)
    p90 = ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]
    cv = (statistics.pstdev(samples) / statistics.fmean(samples)) if len(samples) > 1 else 0.0
    return {"median": median, "p90": p90, "cv": cv, "samples": samples}


def cli(*args: str) -> None:
    """Run the CLI and *show what it said* when it fails.

    The original used `check=True` with captured output, so a failing child
    surfaced as `CalledProcessError: returned non-zero exit status 1` and
    nothing else. That silent harness hid a red perf job for as long as it
    existed: the child was reporting "golden set: 0 intents" — an empty
    catalogue — and the harness threw the explanation away.
    """
    r = subprocess.run([sys.executable, str(ROOT / "eccx"), *args],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode:
        said = (r.stderr.strip() or r.stdout.strip())[-800:]
        raise SystemExit(
            f"`eccx {' '.join(args)}` exited {r.returncode}. A budget timed on "
            f"a command that fails measures nothing. The child said:\n{said}")


def semantic_available() -> bool:
    """Is the embedding model actually importable here?

    `recall --semantic` degrades to lexical without it — no error, no warning,
    just a fast number that looks like a good result.
    """
    try:
        import fastembed  # noqa: F401
    except Exception:
        return False
    return True


def ensure_catalogue() -> int:
    """Make sure the *pinned* catalogue is on disk, or say why it is not.

    The benchmark has exactly one fixture and it cannot measure anything
    without it. Two failures taught this function its shape:

    1. it used to assume the fixture was there — fine on a developer machine,
       false in CI, where nothing cloned ~/ECC unless the workflow said so;
    2. the fix cloned upstream HEAD, which means the fixture *moved*: on
       2026-10-30 it went from 607 to 611 documents between two runs twenty
       minutes apart, and a property test flipped from green to red with no
       change to this repository.

    So the fetch is by commit (`ecc-pin.txt`, via tools/fetch_ecc.sh), it
    announces itself, and ECCX_BENCH_NO_FETCH=1 turns it back into a hard
    failure for anyone who needs a hermetic run.
    """
    if (ECC_ROOT / "skills").is_dir():
        return len(list((ECC_ROOT / "skills").iterdir()))
    if os.environ.get("ECCX_BENCH_NO_FETCH"):
        raise SystemExit(
            f"catalogue absent sous {ECC_ROOT} et ECCX_BENCH_NO_FETCH est posé : "
            f"ces budgets mesureraient le routage d'un corpus vide.\n"
            f"  tools/fetch_ecc.sh {ECC_ROOT}")
    script = ROOT / "tools" / "fetch_ecc.sh"
    print(f"catalogue absent sous {ECC_ROOT} — récupération du commit épinglé")
    r = subprocess.run([str(script), str(ECC_ROOT)], text=True)
    if r.returncode:
        raise SystemExit(f"tools/fetch_ecc.sh a échoué ({r.returncode}) : "
                         f"sans catalogue, ces budgets ne mesurent rien.")
    return len(list((ECC_ROOT / "skills").iterdir()))


def require_catalogue(idx: dict) -> int:
    """Refuse to time routing against a catalogue that is not there.

    With ECC_ROOT missing (no ~/ECC, no $ECC_ROOT), the indexer returns a
    handful of local documents and `eval` reports 0 % recall — a number that
    looks like a catastrophic regression and is really a missing clone.
    """
    skills = sum(1 for d in idx.get("docs", []) if d.get("kind") == "skill")
    if skills < 100:
        raise SystemExit(
            f"catalogue absent : {skills} skills indexés, il en faut ~311. "
            f"ECC_ROOT={__import__('os').environ.get('ECC_ROOT', '~/ECC')} — "
            f"ces budgets mesureraient le routage d'un corpus vide.\n"
            f"  git clone --depth 1 https://github.com/affaan-m/ECC ~/ECC && ./eccx index")
    return skills


def build_benchmarks() -> list[dict]:
    ensure_catalogue()
    idx = indexer.load()
    require_catalogue(idx)
    queries = [c["q"] for c in evaluate.load_golden(ROOT / "evals" / "routing.jsonl")][:25]
    long_query = "reduce the cost of our api calls without breaking behaviour"
    q = queries[0]

    return [
        {
            "name": "index build (607 docs, 4 906 sections)",
            "budget_s": 2.97,   # median 0.988s  p90 1.037s
            "fn": lambda: indexer.build(),
        },
        {
            "name": "router.score, full catalogue, k=15",
            "budget_s": 0.05,   # median 0.01s  p90 0.011s
            "fn": lambda: router.score(idx, long_query, top=15),
        },
        {
            # Declared SLO rather than 3x-measured: 200 ms/query is the point
            # where `eccx recall` stops feeling instant, so that is the line.
            "name": "router.score x25 queries (200 ms/query SLO)",
            "budget_s": 0.48,   # median 0.161s  p90 0.189s
            "fn": lambda: [router.score(idx, x, top=15) for x in queries],
        },
        {
            "name": "rerank.shortlist k=30",
            "budget_s": 0.05,   # median 0.012s  p90 0.015s
            "fn": lambda: rerank.shortlist(idx, long_query, k=30),
        },
        {
            "name": "rerank.resolve, cold cache (3 depths)",
            "budget_s": 0.07,   # median 0.024s  p90 0.029s
            "fn": lambda: rerank.resolve(idx, "a query that was never judged at all"),
        },
        {
            "name": "render_bundle, 3 500-token budget",
            "budget_s": 0.05,   # median 0.007s  p90 0.008s
            "fn": lambda: router.render_bundle(router.score(idx, q, top=4),
                                               budget_tokens=3500, query=q),
        },
        {
            "name": "eccx stats (process start incl.)",
            "budget_s": 0.17,   # median 0.058s  p90 0.062s
            "fn": lambda: cli("stats"),
        },
        {
            # --no-semantic is not a shortcut, it is the only way this budget
            # means the same thing on two machines. `recall` defaults to
            # semantic, which silently loads the model *when vectors happen to
            # exist on the host* — 0.17 s here, 1.27 s with the model, and a
            # different number again on the runner. The shipped default is
            # lexical (see docs/CORPUS-RESTAURANT-SUITE.md), so that is timed.
            "name": "eccx recall --k 2, lexical (process start incl.)",
            "budget_s": 0.52,   # median 0.172s  p90 0.217s
            "fn": lambda: cli("recall", "debug a flaky python test", "--k", "2",
                              "--no-semantic"),
        },
        *([{
            # What turning the model on actually costs, declared rather than
            # implied. Not part of the shipped default; kept so the price is
            # visible next to the benefit, which the corpus measurement says
            # is zero.
            #
            # Gated on the model being importable. Without fastembed, `recall
            # --semantic` degrades to lexical *silently*: measured at 0.153 s
            # in a bare venv against 1.271 s with the model, i.e. a budget
            # that passes 25x under its limit while measuring nothing. A gate
            # that cannot fail is not a gate, so this one is simply absent
            # when the thing it prices is absent — and the run says so.
            "name": "eccx recall --k 2, sémantique (modèle inclus)",
            "budget_s": 3.81,   # median 1.271s  p90 1.316s
            "fn": lambda: cli("recall", "debug a flaky python test", "--k", "2",
                              "--semantic"),
        }] if semantic_available() else []),
        {
            "name": "eccx eval, 50 dev cases, lexical",
            "budget_s": 1.33,   # median 0.445s  p90 0.451s
            # --no-semantic makes the label true. With vectors present on the
            # machine this used to time the semantic path and call it lexical;
            # a benchmark whose inputs depend on the host is not a benchmark.
            "fn": lambda: cli("eval", "--quiet", "--no-semantic"),
        },
    ]


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    update = "--update" in argv
    if "COVERAGE_PROCESS_START" in __import__("os").environ:
        print("refusing to measure under coverage instrumentation "
              "(see docs/QUALITY.md §24)", file=sys.stderr)
        return 2

    rows, failures = [], []
    for bench in build_benchmarks():
        st = sample(bench["fn"])
        measured = st["median"]
        over = measured > bench["budget_s"]
        if over:
            failures.append(bench["name"])
        rows.append({"name": bench["name"], "measured_s": round(measured, 4),
                     "p90_s": round(st["p90"], 4), "cv": round(st["cv"], 3),
                     "budget_s": bench["budget_s"], "over": over,
                     "headroom": round(bench["budget_s"] / measured, 2) if measured else 0.0})

    if as_json:
        print(json.dumps({"rows": rows, "failures": failures}, indent=1))
    elif update:
        print("# regenerated by `python3 perf/budgets.py --update`")
        print("# rule: max(3 x median, 1.5 x p90, 0.05 s)")
        for r in rows:
            print(f'            "budget_s": {declared_budget(r["measured_s"], r["p90_s"])},'
                  f'   # median {r["measured_s"]:.3f}s  p90 {r["p90_s"]:.3f}s  cv {r["cv"]:.0%}')
    else:
        width = max(len(r["name"]) for r in rows) + 2
        print(f"{'benchmark':<{width}}{'median':>9}{'p90':>8}{'cv':>6}"
              f"{'budget':>9}{'headroom':>10}  verdict")
        print("-" * (width + 46))
        for r in rows:
            verdict = "FAIL" if r["over"] else "ok"
            print(f"{r['name']:<{width}}{r['measured_s']:>8.3f}s"
                  f"{r['p90_s']:>7.3f}s{r['cv']:>5.0%}"
                  f"{r['budget_s']:>8.2f}s{r['headroom']:>9.1f}x  {verdict}")
        print()
        if failures:
            print(f"{len(failures)} budget(s) exceeded: {', '.join(failures)}")
            return 1
        worst = max(r["headroom"] for r in rows)
        print(f"all {len(rows)} budgets met (median of {REPEATS} runs, "
              f"cold process, no instrumentation)")
        if not semantic_available():
            print("1 budget non mesuré : le sémantique, fastembed absent — "
                  "et sans modèle `recall --semantic` retombe sur le lexical "
                  "sans le dire")
        print(f"loosest budget: {worst:.1f}x its median — a regression smaller "
              f"than that is invisible here")
    return 1 if failures else 0


if __name__ == "__main__":
    # This guard is load-bearing: without it the module parses, imports and
    # exits 0 having measured nothing — a budget gate that cannot fail. It was
    # removed by a refactor of main() and went unnoticed for one commit.
    raise SystemExit(main(sys.argv[1:]))
