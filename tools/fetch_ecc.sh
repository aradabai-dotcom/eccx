#!/usr/bin/env bash
# Put the *pinned* upstream catalogue at DEST, or verify it is already there.
#
#   tools/fetch_ecc.sh [DEST]        # default: $ECC_ROOT, else ~/ECC
#
# Why a pin and not `git clone --depth 1`: the suite's property tests draw
# their queries from the catalogue's own vocabulary, so a catalogue that
# changes under CI changes the tests. On 2026-10-30 upstream moved four
# commits (607 -> 611 docs) between two runs twenty minutes apart and a green
# property test went red without a line of this repository changing. Every
# routing number in the docs was also measured against a specific commit, and
# a moving target makes them unreproducible.
#
# Exit codes: 0 ok, 2 usage/environment problem, 3 DEST exists and is not ours
# to overwrite (refusing to delete someone's checkout).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PIN="$(grep -vE '^[[:space:]]*(#|$)' "$ROOT/ecc-pin.txt" | tr -d '[:space:]')"
if ! printf '%s' "$PIN" | grep -qE '^[0-9a-f]{40}$'; then
  echo "[fetch_ecc] ecc-pin.txt ne contient pas un SHA de 40 caractères : '$PIN'" >&2
  exit 2
fi

DEST="${1:-${ECC_ROOT:-$HOME/ECC}}"

if [ -d "$DEST/.git" ] && [ "$(git -C "$DEST" rev-parse HEAD 2>/dev/null)" = "$PIN" ]; then
  echo "[fetch_ecc] $DEST déjà à $PIN"
  exit 0
fi

if [ -e "$DEST" ] && [ ! -d "$DEST/.git" ]; then
  echo "[fetch_ecc] $DEST existe et n'est pas un dépôt git : je ne l'écrase pas." >&2
  echo "[fetch_ecc] déplace-le, ou passe un autre chemin en argument." >&2
  exit 3
fi

if [ ! -d "$DEST/.git" ]; then
  mkdir -p "$DEST"
  git -C "$DEST" init -q
  git -C "$DEST" remote add origin https://github.com/affaan-m/ECC 2>/dev/null || true
fi
echo "[fetch_ecc] récupération de $PIN dans $DEST"
git -C "$DEST" fetch -q --depth 1 origin "$PIN"
git -C "$DEST" checkout -q --detach "$PIN"
echo "[fetch_ecc] $DEST = $(git -C "$DEST" rev-parse --short HEAD)"
