#!/usr/bin/env bash
# Full verification gate. Fails loudly; never silently skips a check.
set -uo pipefail
cd "$(dirname "$0")"

MIN_COVERAGE="${MIN_COVERAGE:-85}"

# Self-heal: pip packages are not part of the workspace snapshot.
if ! python3 -c "import coverage" >/dev/null 2>&1; then
  echo "[run-checks] installing coverage (not persisted between sessions)…"
  pip install --quiet coverage >/dev/null 2>&1 || true
fi

echo "== unit tests =="
if python3 -c "import coverage" >/dev/null 2>&1; then
  COVERAGE_PROCESS_START="$PWD/.coveragerc" \
  PYTHONPATH="$PWD/tools/cov_boot:${PYTHONPATH:-}" \
  python3 -m coverage run --source=eccxlib -m unittest discover tests "$@"
  tests_rc=$?

  echo
  echo "== coverage (includes CLI subprocesses, branch coverage) =="
  python3 -m coverage combine >/dev/null 2>&1
  python3 -m coverage report
  pct=$(python3 -m coverage report --format=total 2>/dev/null | tr -dc '0-9.')
  echo
  if [ -n "${pct}" ] && python3 -c "import sys; sys.exit(0 if float('$pct') >= $MIN_COVERAGE else 1)"; then
    echo "coverage gate: ${pct}% >= ${MIN_COVERAGE}% PASS"
    cov_rc=0
  else
    echo "coverage gate: ${pct:-?}% < ${MIN_COVERAGE}% FAIL"
    cov_rc=1
  fi
else
  echo "[run-checks] coverage unavailable — running tests without the gate" >&2
  python3 -m unittest discover tests "$@"
  tests_rc=$?
  cov_rc=0
fi

echo
echo "== upstream ECC tree byte-identical to its pinned commit =="
# The whole adapter rests on "we did not touch upstream": if the clone drifts,
# every measurement below is measuring a fork nobody reviewed. This caught
# `npm install` rewriting upstream's yarn.lock on every reinstall.
if git -C "$HOME/ECC" rev-parse --git-dir >/dev/null 2>&1; then
  # The workspace snapshot drops file modes, so every executable in the clone
  # comes back as 0644 and `git status` shows 72 phantom modifications after a
  # restart. Compare content, not modes — otherwise the gate cries wolf from
  # the second session on and stops being read.
  dirty=$(git -C "$HOME/ECC" -c core.fileMode=false status --porcelain | wc -l | tr -d ' ')
  head_sha=$(git -C "$HOME/ECC" rev-parse --short HEAD)
  if [ "$dirty" = "0" ]; then
    echo "ECC @ $head_sha clean"
    upstream_rc=0
  else
    echo "ECC @ $head_sha has $dirty modified file(s):"
    git -C "$HOME/ECC" -c core.fileMode=false status --porcelain | head -10
    upstream_rc=1
  fi
else
  echo "[run-checks] ~/ECC is not a git clone — cannot verify upstream" >&2
  upstream_rc=1
fi

echo
echo "== definition of done per catalogue gap (evals/gaps.json) =="
./eccx gaps
gaps_rc=$?

echo
echo "== local overlay conforms to ECC's skill contract =="
./eccx validate
conf_rc=$?

echo
echo "== skill frontmatter parser cross-checked against js-yaml =="
./eccx audit --sample 20 >/dev/null
audit_rc=$?

# Embeddings are optional: without `fastembed` (or offline) every check below
# still runs, on the lexical router. The gate must not become unrunnable on a
# machine that cannot download a 130 MB model — but where the vectors *can* be
# built, they must be current, because a stale vector file is silently wrong.
echo
echo "== semantic vectors (optional; skipped without fastembed) =="
./eccx vectors >/dev/null 2>&1 && echo "  vectors current" \
  || echo "  not built (fastembed absent or offline) — lexical routing"

# The bars below were measured with the semantic layer on. Running them on a
# lean install made the gate fail for a reason that is not a regression, and a
# gate that cries wolf is a gate people learn to ignore. So the mode is
# detected once, and the lexical bars are the *measured* lexical numbers minus
# a margin — not a hopeful guess. CI installs `[dev]` (fastembed included) and
# therefore always takes the full branch; `--lexical` forces this one.
if ./eccx vectors >/dev/null 2>&1; then
  MODE="semantic"
else
  MODE="lexical"
fi
[ "${ECCX_LEXICAL:-0}" = "1" ] && MODE="lexical"
echo "  gate mode: $MODE"

echo
echo "== routing quality bar (dev set) =="
./eccx eval --quiet --min-recall 0.9
eval_rc=$?

# The dev set above is the set the parameters were tuned on: 98 % recall@5 there
# says nothing about a query nobody has seen. This is the only line in the gate
# that measures generalisation, and it exists because the router was measured at
# 30.9 % @1 on unseen phrasing while every check stayed green.
#
# `heldout5` was written before any diagnosis and measured once. It is now
# *burnt*: it is a regression bar, not a held-out set. The next substantive
# ranking change needs a fresh set, written before looking at anything.
echo
echo "== generalisation floor (evals/heldout5.jsonl, never used for tuning) =="
if [ "$MODE" = "semantic" ]; then H5_3=0.38; else H5_3=0.30; fi
./eccx eval --file evals/heldout5.jsonl --k 3 --min-recall $H5_3 --quiet
heldout_rc=$?

# The depth the product is actually used at. `--min-recall` defaults to 0.90, so
# asking for it at k=20 is a real floor: the shortlist must keep containing the
# answer 9 times out of 10 on a set nobody tuned against.
if [ "$MODE" = "semantic" ]; then H5_20=0.70; else H5_20=0.55; fi
./eccx eval --file evals/heldout5.jsonl --k 20 --min-recall $H5_20 --quiet
shortlist_rc=$?

# `heldout7` (59 queries) was written in one sitting to test section-level
# retrieval, and measured exactly once: 16 -> 22 at @1, 6 gains / 0 losses,
# p = 0.031. It then became a regression bar like heldout5. Floors are set
# below the measured values, not at them — a bar set at the measurement fails
# on the next run for reasons that have nothing to do with routing.
if [ "$MODE" = "semantic" ]; then H7_1=0.33; else H7_1=0.18; fi
./eccx eval --file evals/heldout7.jsonl --k 1 --min-recall $H7_1 --quiet
sealed1_rc=$?
if [ "$MODE" = "semantic" ]; then H7_20=0.70; else H7_20=0.62; fi
./eccx eval --file evals/heldout7.jsonl --k 20 --min-recall $H7_20 --quiet
sealed20_rc=$?

# `heldout8` (40 queries) is the second blind batch. `heldout7+8` is the test
# that decided the matter: 10 gains / 2 losses at @1, p = 0.039, on 99 queries
# no parameter had ever seen.
if [ "$MODE" = "semantic" ]; then H8_1=0.22; else H8_1=0.12; fi
./eccx eval --file evals/heldout8.jsonl --k 1 --min-recall $H8_1 --quiet
sealed8_rc=$?

# `heldout9` (50 queries) was the blind set for the cross-encoder reranker.
# That reranker lost 51 queries and won 5, so the set now guards the shipped
# ranking against a future "let's just reorder the top 20" idea.
if [ "$MODE" = "semantic" ]; then H9_1=0.34; else H9_1=0.20; fi
./eccx eval --file evals/heldout9.jsonl --k 1 --min-recall $H9_1 --quiet
sealed9_rc=$?
if [ "$MODE" = "semantic" ]; then H9_20=0.80; else H9_20=0.68; fi
./eccx eval --file evals/heldout9.jsonl --k 20 --min-recall $H9_20 --quiet
sealed9b_rc=$?

# The suite tests `render_bundle`; only this tests the *promise*, through the
# CLI, banner and route map included. `--k 8 --budget 400` emitted 1 983 tokens
# and every check stayed green, which is exactly why this line exists.
# `--corpus` is the whole point of the product: routing someone's own notes.
# It is also the newest code, and the first version sent `eccx vectors` to the
# ECC index while writing into the corpus state directory. A CLI-level smoke
# test on a throwaway directory is the only thing that sees the whole path.
echo
echo "== routing over a user corpus (build, recall, eval) =="
python3 tools/corpus_smoke.py
corpus_rc=$?

echo
echo "== token budget is a hard promise (CLI, k=8, budget 400/1000) =="
python3 tools/budget_smoke.py
budget_rc=$?

echo
if [ $tests_rc -eq 0 ] && [ $cov_rc -eq 0 ] && [ $upstream_rc -eq 0 ] \
   && [ $gaps_rc -eq 0 ] && [ $conf_rc -eq 0 ] && [ $audit_rc -eq 0 ] \
   && [ $eval_rc -eq 0 ] && [ $heldout_rc -eq 0 ] && [ $shortlist_rc -eq 0 ] \
   && [ $sealed1_rc -eq 0 ] && [ $sealed20_rc -eq 0 ] && [ $sealed8_rc -eq 0 ] \
   && [ $sealed9_rc -eq 0 ] && [ $sealed9b_rc -eq 0 ] && [ $corpus_rc -eq 0 ] \
   && [ $budget_rc -eq 0 ]; then
  echo "ALL CHECKS PASSED"
  echo
  echo "Not in this gate, by design:"
  echo "  tools/mutate.sh      mutation score   (~21 min, 2 639 mutants, measured 80.4%)"
  echo "  tools/mutation_audit.py  audits the mutation score itself (~4 min)"
  echo "  python3 perf/budgets.py   perf budgets (~30 s, timing-sensitive)"
  exit 0
fi
echo "FAILURES (tests=$tests_rc coverage=$cov_rc upstream=$upstream_rc gaps=$gaps_rc conformity=$conf_rc audit=$audit_rc eval=$eval_rc heldout=$heldout_rc shortlist=$shortlist_rc budget=$budget_rc)"
exit 1
