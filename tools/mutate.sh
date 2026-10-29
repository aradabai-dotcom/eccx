#!/usr/bin/env bash
# Mutation testing — "does the suite notice when the code is wrong?"
#
# Coverage answers "was this line executed?". Mutation testing answers the
# question that actually matters, and it is the only check in this repo that
# can fail because a test is *vacuous*. It found 185 surviving mutants inside
# `evaluate.run`, whose only tests asserted `cases == 0` — 100% covered, 0%
# verified.
#
# Cost: ~3 minutes for 1 118 mutants on 2 vCPU. That is why it is NOT part of
# run-checks.sh (which must stay in the 2-5 minute range): this is a
# pre-release / per-change-to-the-core gate, run deliberately.
#
# Usage:
#   tools/mutate.sh              # run (resumes from the cache if interrupted)
#   tools/mutate.sh report       # re-print the score from the last run
#   MIN_SCORE=0.85 tools/mutate.sh
set -uo pipefail
cd "$(dirname "$0")/.."

# Floor, not target. The floor moved once, on purpose, and the reason is
# recorded: the first 72.2 % was measured on util+rerank+evaluate only. Adding
# router.py and indexer.py (the code that actually ranks and indexes) doubled
# the mutant count to 2421 and dropped the score to 69.0 %. A floor set to the
# old, narrower number would have been a lie about the product.
#   69.0 % measured 2026-10-28, scope = util, rerank, evaluate, router, indexer.
#   79.0 % after the triage in docs/MUTATION-TRIAGE.md (468 survivors left).
# Floor = measured - 2 points: enough to absorb the +/-1 mutant jitter that
# mutmut shows between identical runs, small enough that any real regression
# (a dropped test class costs ~1 point each) trips it.
# The gate's job is to stop the number from *falling* while survivors are
# triaged one by one (docs/MUTATION-TRIAGE.md). 80 % remains the goal.
MIN_SCORE="${MIN_SCORE:-0.77}"
REPORT="docs/MUTATION.md"

if ! python3 -c "import mutmut" >/dev/null 2>&1; then
  echo "[mutate] installing mutmut (pip packages are not part of the snapshot)…"
  pip install --quiet mutmut >/dev/null 2>&1 || { echo "cannot install mutmut"; exit 2; }
fi

if [ "${1:-run}" != "report" ]; then
  echo "== mutating $(grep -c . pyproject.toml >/dev/null; echo 'util.py, rerank.py, evaluate.py') =="
  echo "   selection: fast unit tests only (see [tool.mutmut] in pyproject.toml)"
  python3 -m mutmut run --max-children 2
fi

# --- score ---------------------------------------------------------------
# `results --all` lists every mutant with its status in one pass:
#   killed / survived / timeout / no tests / not checked
# "no tests" is excluded from the denominator on purpose: it is a coverage
# fact, already reported by the coverage gate, and counting it twice would let
# a low score hide behind it.
python3 -m mutmut results --all true > /tmp/mutmut-all.txt 2>/dev/null

# Counted in one Python pass. `grep -c` exits 1 when it matches nothing, so the
# usual `$(grep -c ... || echo 0)` yields "0\n0" and every later comparison dies
# with "integer expression expected" — a gate that crashes on the empty case is
# a gate that never reports the empty case.
counts=$(python3 - <<'PYEOF'
import re, sys
k = s = t = n = u = tot = 0
for line in open("/tmp/mutmut-all.txt", encoding="utf-8"):
    # The status may contain a space ("no tests"), so grab the whole tail.
    m = re.match(r"^\s*\S+__mutmut_\d+: (.+?)\s*$", line)
    if not m:
        continue
    tot += 1
    st = m.group(1).strip()
    if st == "killed": k += 1
    elif st == "survived": s += 1
    elif st == "timeout": t += 1
    elif st == "no tests": n += 1
    elif st == "not checked": u += 1
print(tot, k, s, t, n, u)
PYEOF
)
read -r TOTAL killed survivors timeouts notests unchecked <<< "$counts"

# A gate that reports 0 % when it simply has no data is worse than no gate: it is
# indistinguishable from a real collapse. Refuse, and write nothing.
if [ "${TOTAL:-0}" -eq 0 ]; then
  echo "[mutate] no data: .mutmut-cache is missing or empty." >&2
  echo "[mutate] run tools/mutate.sh (without 'report') first; nothing was written." >&2
  exit 3
fi
if [ "${unchecked:-0}" -gt 0 ]; then
  echo
  echo "[mutate] run incomplete: $unchecked/$TOTAL mutants not checked." >&2
  echo "[mutate] re-run tools/mutate.sh — mutmut resumes from its cache." >&2
  exit 2
fi
covered=$(( killed + survivors + timeouts ))
pct=$(python3 -c "print(f'{($killed / $covered * 100) if $covered else 0:.1f}')")

echo
echo "mutants            $TOTAL"
echo "  killed           $killed"
echo "  survived         $survivors"
echo "  timeout          $timeouts"
echo "  no test (uncovered line, already counted by the coverage gate) $notests"
echo "mutation score     ${pct}%  (killed / covered mutants)"

{
  echo "# Mutation testing — journal"
  echo
  echo "Généré par \`tools/mutate.sh\`, $(date -u '+%Y-%m-%dT%H:%M:%SZ')."
  echo
  echo "| mesure | valeur |"
  echo "|---|---|"
  echo "| mutants générés | $TOTAL |"
  echo "| tués | $killed |"
  echo "| survivants | $survivors |"
  echo "| timeout | $timeouts |"
  echo "| sans test (ligne non couverte) | $notests |"
  echo "| **score de mutation** | **${pct} %** |"
  echo "| seuil du harnais | $(python3 -c "print(f'{float('$MIN_SCORE')*100:.0f} %')") |"
  echo
  echo "Score = tués / (tués + survivants + timeouts). Les mutants « sans test »"
  echo "sont exclus : ils mesurent la couverture, déjà gardée par le gate de"
  echo "couverture, et les compter deux fois permettrait de maquiller le score."
  echo
  echo "## Survivants par fonction"
  echo
  echo '```'
  python3 -m mutmut results 2>/dev/null | grep survived \
    | sed -E 's/.*eccxlib\.([a-z_]+)\.(x?[a-z_0-9]+)__mutmut.*/\1.\2/' \
    | sort | uniq -c | sort -rn | head -20
  echo '```'
  echo
  echo "## Comment lire ce chiffre"
  echo
  echo "Un score de 100 % est un objectif de mauvaise foi : il y a toujours des"
  echo "mutations équivalentes (changer \`<\` en \`<=\` sur une borne que les données"
  echo "ne touchent jamais). Ce qui compte :"
  echo
  echo "1. le score **ne baisse pas** d'une passe à l'autre ;"
  echo "2. chaque survivant examiné est classé *équivalent* (justifié) ou *trou réel*"
  echo "   (corrigé par un test) — jamais ignoré."
} > "$REPORT"

echo "rapport écrit dans $REPORT (tri manuel : docs/MUTATION-TRIAGE.md)"

if python3 -c "import sys; sys.exit(0 if $pct/100 >= $MIN_SCORE else 1)"; then
  echo "mutation gate: ${pct}% >= $(python3 -c "print(f'{float('$MIN_SCORE')*100:.0f}')")% PASS"
  exit 0
fi
echo "mutation gate: ${pct}% < $(python3 -c "print(f'{float('$MIN_SCORE')*100:.0f}')")% FAIL"
echo "→ add tests that assert *behaviour*, not just that code ran. See docs/QUALITY.md §27."
exit 1
