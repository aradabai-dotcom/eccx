#!/usr/bin/env bash
# Installe les 5 dépendances de production de la base vendue et vérifie que le
# routeur d'ECC démarre dessus. `node_modules` n'est jamais versionné.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$here/../vendor/ecc"

[ -f "$root/package.json" ] || { echo "base absente : $root" >&2; exit 2; }
cd "$root"

if [ ! -d node_modules ]; then
  echo "installation des dépendances de production…"
  npm ci --omit=dev --silent
fi

entries=$(node -e '
const { routingEntries } = require("./scripts/lib/context-selection.js");
process.stdout.write(String(routingEntries({ repoRoot: process.cwd() }).entries.length));
')

echo "routeur ECC opérationnel sur la base vendue : $entries entrées"
[ "$entries" -gt 0 ] || { echo "le routeur n'a rendu aucune entrée" >&2; exit 1; }
