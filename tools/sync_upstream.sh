#!/usr/bin/env bash
# Récupère un dossier ou un fichier de l'amont dans la base vendue, au commit
# épinglé — jamais depuis la tête de branche.
#
#   ./tools/sync_upstream.sh --add pi docs            # ajoute des dossiers
#   ./tools/sync_upstream.sh --add scripts/ci/pi-core-load-test.js
#   ./tools/sync_upstream.sh --list                   # ce que l'amont contient
#   ./tools/sync_upstream.sh --restore scripts/lib    # remet un dossier d'origine
#
# Pourquoi ce script existe : PROVENANCE.md y renvoyait avant qu'il existe. Une
# documentation qui nomme un outil absent est pire qu'une doc muette — elle fait
# perdre une heure à celui qui la croit.
#
# Ce qu'il ne fait pas : toucher à BASE.sha256. Le manifeste garde l'empreinte
# de la copie initiale, donc `tools/base_diff.py` continue d'afficher ce que
# vous avez ajouté ou supprimé par rapport à elle.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$here/.."
base="$root/vendor/ecc"
pin_file="$root/ecc-pin.txt"

die() { echo "$*" >&2; exit 2; }

[ -f "$pin_file" ] || die "ecc-pin.txt absent"
commit=$(grep -v '^[[:space:]]*#' "$pin_file" | grep -v '^[[:space:]]*$' | head -1 | tr -d '[:space:]')
[ -n "$commit" ] || die "ecc-pin.txt ne contient aucun commit"
echo "amont épinglé : $commit"

mode="${1:-}"
[ -n "$mode" ] || die "usage : $0 --add PATH... | --restore PATH... | --list"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

fetch_paths() {
  # git ne sait pas sortir un sous-dossier sans cloner ; on fait un clone
  # partiel, borné au commit, puis on copie ce qui est demandé.
  git clone --quiet --filter=blob:none --no-checkout \
      https://github.com/affaan-m/ECC "$tmp/up" 2>/dev/null || die "clone impossible"
  git -C "$tmp/up" checkout --quiet "$commit" || die "commit $commit introuvable"
}

case "$mode" in
  --list)
    fetch_paths
    ( cd "$tmp/up" && for d in */; do printf "  %-14s %s\n" "${d%/}" "$(du -sh "$d" | cut -f1)"; done )
    ;;

  --add)
    shift
    [ $# -gt 0 ] || die "--add attend au moins un chemin"
    fetch_paths
    for p in "$@"; do
      src="$tmp/up/$p"
      [ -e "$src" ] || die "$p n'existe pas dans l'amont @ $commit"
      mkdir -p "$base/$(dirname "$p")"
      cp -R "$src" "$base/$p"
      echo "  ajouté  $p"
    done
    echo
    echo "pensez à : ./tools/vendor_bootstrap.sh   (dépendances Node)"
    echo "           python3 tools/base_diff.py     (ce que la base a de plus)"
    ;;

  --restore)
    shift
    [ $# -gt 0 ] || die "--restore attend au moins un chemin"
    fetch_paths
    for p in "$@"; do
      src="$tmp/up/$p"
      [ -e "$src" ] || die "$p n'existe pas dans l'amont @ $commit"
      rm -rf "${base:?}/$p"
      mkdir -p "$base/$(dirname "$p")"
      cp -R "$src" "$base/$p"
      echo "  restauré depuis l'amont  $p"
    done
    ;;

  *)
    die "mode inconnu : $mode (--add | --restore | --list)"
    ;;
esac
