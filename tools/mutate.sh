#!/usr/bin/env bash
# Mutation testing — "does the suite notice when the code is wrong?"
#
# Coverage answers "was this line executed?". Mutation testing answers the
# question that actually matters, and it is the only check in this repo that
# can fail because a test is *vacuous*. It found 185 surviving mutants inside
# `evaluate.run`, whose only tests asserted `cases == 0` — 100% covered, 0%
# verified.
#
# Usage:
#   tools/mutate.sh                     # full scope, gating, ~90 min in CI
#   tools/mutate.sh report              # re-print the score from the last full run
#   tools/mutate.sh --changed [BASE]    # only what the diff touched, advisory
#   tools/mutate.sh --only a.py b.py    # explicit scope, advisory (sharding)
#   MIN_SCORE=0.85 tools/mutate.sh
#
# Why three modes instead of one: the full run answers "is the whole suite
# still serious?" and belongs on a schedule. A pull request needs the answer in
# minutes, about the lines it actually changed. Both are mutation testing; only
# the second one can be a per-change gate, and pretending a 90-minute job is
# one is how it became `workflow_dispatch`-only and therefore never read.
#
# The diff-scoped run happens in a throwaway `git worktree` with its own
# `.mutmut-cache`. Two reasons, both learned here: mutmut takes its scope from
# `pyproject.toml` (it has no `--paths` flag), and a shared cache would keep
# reporting mutants from every earlier full run, silently turning a 400-mutant
# score into a 2 400-mutant one.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# The suite indexes the real catalogue (TestRerank, TestIndexerBuild, the CLI
# tests), so a runner without ~/ECC fails at *collection* — before a single
# mutant is tested — with a CatalogueAbsent that has nothing to do with
# mutation. Same rule as perf/budgets.py: a check that needs a fixture fetches
# it, announces that it did, and can be told not to.
ECC_ROOT="${ECC_ROOT:-$HOME/ECC}"
ensure_catalogue() {
  [ -d "$ECC_ROOT/skills" ] && return 0
  if [ "${ECCX_BENCH_NO_FETCH:-0}" = "1" ]; then
    echo "[mutate] catalogue absent sous $ECC_ROOT et ECCX_BENCH_NO_FETCH est posé." >&2
    echo "[mutate] git clone --depth 1 https://github.com/affaan-m/ECC $ECC_ROOT" >&2
    exit 2
  fi
  echo "[mutate] catalogue absent sous $ECC_ROOT — clonage de https://github.com/affaan-m/ECC"
  git clone --quiet --depth 1 https://github.com/affaan-m/ECC "$ECC_ROOT" || {
    echo "[mutate] clonage impossible : la suite ne peut pas être collectée." >&2; exit 2; }
}

MIN_SCORE="${MIN_SCORE:-0.77}"
MIN_PCT=$(python3 -c "print(round(float('$MIN_SCORE')*100))")
REPORT="docs/MUTATION.md"
MAX_CHILDREN="${MAX_CHILDREN:-2}"

ensure_mutmut() {
  if ! python3 -c "import mutmut" >/dev/null 2>&1; then
    echo "[mutate] installing mutmut (pip packages are not part of the snapshot)…"
    pip install --quiet mutmut >/dev/null 2>&1 || { echo "cannot install mutmut"; exit 2; }
  fi
}

# counts <dir> → "total killed survived timeout notests unchecked"
# `results --all` lists every mutant with its status in one pass. "no tests" is
# excluded from the denominator on purpose: it is a coverage fact, already
# reported by the coverage gate, and counting it twice would let a low score
# hide behind it.
counts() {
  ( cd "$1" && python3 -m mutmut results --all true 2>/dev/null ) > /tmp/mutmut-all.txt
  python3 - <<'PYEOF'
import re
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
}

pct_of() { python3 -c "print(f'{($1 / $2 * 100) if $2 else 0:.1f}')"; }

# ---------------------------------------------------------------- full run
if [ "${1:-run}" = "report" ]; then
  ensure_mutmut
  read -r TOTAL killed survivors timeouts notests unchecked <<< "$(counts "$ROOT")"
  if [ "${TOTAL:-0}" -eq 0 ]; then
    echo "[mutate] no data: .mutmut-cache is missing or empty." >&2
    echo "[mutate] run tools/mutate.sh first; nothing was written." >&2
    exit 3
  fi
  covered=$(( killed + survivors + timeouts ))
  echo "mutants $TOTAL · killed $killed · survived $survivors · score $(pct_of "$killed" "$covered")%"
  exit 0
fi

# ------------------------------------------------------- scoped runs (PR / shard)
SCOPE_ARGS=()
BASE=""
case "${1:-run}" in
  --changed)
    BASE="${2:-}"
    ;;
  --only)
    shift
    SCOPE_ARGS=("$@")
    ;;
esac

if [ "${1:-run}" = "--changed" ] || [ "${1:-run}" = "--only" ]; then
  ensure_mutmut
  if [ "${1}" = "--changed" ]; then
    json=$(python3 tools/mutation_scope.py ${BASE:+--base "$BASE"} --json) || exit 2
    mapfile -t SCOPE_ARGS < <(printf '%s' "$json" | python3 -c \
      "import json,sys; [print(p) for p in json.load(sys.stdin)['scope']]")
    BASE=$(printf '%s' "$json" | python3 -c "import json,sys; print(json.load(sys.stdin)['base'])")
    if [ "${#SCOPE_ARGS[@]}" -eq 0 ]; then
      echo "mutation: aucun module mutable touché depuis $BASE — rien à mesurer, et ce n'est pas un succès."
      exit 0
    fi
  fi
  [ "${#SCOPE_ARGS[@]}" -eq 0 ] && { echo "--only attend au moins un fichier" >&2; exit 2; }

  WT="$(mktemp -d)/mutscope"
  git worktree add -q --detach "$WT" HEAD || { echo "worktree impossible" >&2; exit 2; }
  trap 'git worktree remove --force "$WT" >/dev/null 2>&1' EXIT

  # A worktree is checked out at HEAD, which is *not* what a developer is
  # about to push. Measuring HEAD while the fix sits uncommitted answers a
  # question nobody asked — this cost one wasted 62-second run here, where a
  # strengthened test appeared to change nothing because it was not in the
  # tree under test. Copy every modified/untracked path across, and say so.
  DIRTY=0
  while IFS= read -r path; do
    [ -z "$path" ] && continue
    if [ -e "$path" ]; then mkdir -p "$WT/$(dirname "$path")"; cp "$path" "$WT/$path"; else rm -f "$WT/$path"; fi
    DIRTY=$((DIRTY + 1))
  done < <(git status --porcelain --untracked-files=all | cut -c4-)
  [ "$DIRTY" -gt 0 ] && echo "   arbre de travail : $DIRTY fichier(s) non commité(s) copié(s) dans le worktree"

  python3 - "$WT" "${SCOPE_ARGS[@]}" <<'PYEOF'
import pathlib, sys
wt, scope = pathlib.Path(sys.argv[1]), sys.argv[2:]
p = wt / "pyproject.toml"
s = p.read_text()
start = s.index("only_mutate = [")
end = s.index("]", start) + 1
items = "".join(f'    "{f}",\n' for f in scope)
p.write_text(s[:start] + "only_mutate = [\n" + items + "]" + s[end:])
PYEOF

  ensure_catalogue
  echo "== mutation, portée réduite =="
  echo "   fichiers : ${SCOPE_ARGS[*]}"
  [ -n "$BASE" ] && echo "   base     : $BASE"
  START=$(date +%s)
  ( cd "$WT" && python3 -m mutmut run --max-children "$MAX_CHILDREN" )
  ELAPSED=$(( $(date +%s) - START ))

  read -r TOTAL killed survivors timeouts notests unchecked <<< "$(counts "$WT")"
  if [ "${TOTAL:-0}" -eq 0 ] || [ "${unchecked:-0}" -gt 0 ]; then
    echo "[mutate] run incomplet ou vide ($unchecked/$TOTAL non vérifiés) — aucun chiffre publié." >&2
    exit 2
  fi
  covered=$(( killed + survivors + timeouts ))
  pct=$(pct_of "$killed" "$covered")

  echo
  echo "mutants            $TOTAL  (portée : ${SCOPE_ARGS[*]})"
  echo "  killed           $killed"
  echo "  survived         $survivors"
  echo "  timeout          $timeouts"
  echo "  no test          $notests"
  echo "score de portée    ${pct}%   en ${ELAPSED} s"
  echo

  # Advisory, on purpose. A partial score is not comparable with the floor:
  # nobody has calibrated "what fraction of the mutants in *this file* should
  # die". Failing a PR on an uncalibrated threshold produces one outcome —
  # people ignore the check. The feedback is the survivor list, printed below,
  # and the ratchet stays on the full run.
  echo "portée réduite : informatif. Le seuil (${MIN_PCT}%) ne s'applique"
  echo "qu'au run complet — un score partiel n'est pas comparable à un plancher global."
  ( cd "$WT" && python3 -m mutmut results 2>/dev/null | grep survived ) | head -15
  exit 0
fi

# ---------------------------------------------------------------- full scope
ensure_mutmut
ensure_catalogue
echo "== mutating $(python3 -c "
import pathlib,re
s=pathlib.Path('pyproject.toml').read_text()
m=re.search(r'only_mutate\s*=\s*\[(.*?)\]', s, re.S)
print(', '.join(re.findall(chr(34)+'([^'+chr(34)+']+)'+chr(34), m.group(1))) if m else '?')
") =="
echo "   selection: fast unit tests only (see [tool.mutmut] in pyproject.toml)"
START=$(date +%s)
python3 -m mutmut run --max-children "$MAX_CHILDREN"
ELAPSED=$(( $(date +%s) - START ))

# --- score ---------------------------------------------------------------
read -r TOTAL killed survivors timeouts notests unchecked <<< "$(counts "$ROOT")"

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
pct=$(pct_of "$killed" "$covered")

echo
echo "mutants            $TOTAL   (${ELAPSED} s)"
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
  echo "| durée mesurée | ${ELAPSED} s |"
  echo "| seuil du harnais | ${MIN_PCT} % |"
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
  echo "mutation gate: ${pct}% >= ${MIN_PCT}% PASS"
  exit 0
fi
echo "mutation gate: ${pct}% < ${MIN_PCT}% FAIL"
echo "→ add tests that assert *behaviour*, not just that code ran. See docs/QUALITY.md §27."
exit 1
