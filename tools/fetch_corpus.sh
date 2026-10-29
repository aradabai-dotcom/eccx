#!/usr/bin/env bash
# Fetch the independent validation corpora used in docs/.
#
#   tools/fetch_corpus.sh fastapi [DEST]   # 156 pages, 986 sections
#   tools/fetch_corpus.sh pydantic [DEST]  # 91 pages, 388 sections
#
# Kept out of the repository for two reasons: third-party content, and 19 MB.
# Both are written for humans by people who never heard of this project, which
# is exactly why they are the control: a result on them cannot be an artefact
# of the catalogue the router was tuned on.
set -euo pipefail

WHICH="${1:-fastapi}"
DEST="${2:-/tmp/corpus/$WHICH}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

case "$WHICH" in
  fastapi)  REPO="fastapi/fastapi";  SUB="fastapi-master/docs/en/docs" ;;
  pydantic) REPO="pydantic/pydantic"; SUB="pydantic-main/docs" ;;
  *) echo "corpus inconnu: $WHICH (fastapi|pydantic)" >&2; exit 2 ;;
esac

echo "downloading $REPO..."
curl -sL -o "$TMP/x.tgz" "https://codeload.github.com/$REPO/tar.gz/refs/heads/main"
mkdir -p "$TMP/ex" "$DEST"
tar xzf "$TMP/x.tgz" -C "$TMP/ex" --strip-components=0
src="$TMP/ex/$SUB"
[ -d "$src" ] || { echo "chemin introuvable: $SUB" >&2; exit 1; }
cp -r "$src/." "$DEST/"

n=$(find "$DEST" -name "*.md" | wc -l)
echo "$n markdown files in $DEST"
echo
echo "next:"
echo "  ./eccx corpus build --dir $DEST"
echo "  ./eccx --corpus $DEST vectors            # optional, ~1 min"
echo "  python3 tools/corpus_report.py --corpus $DEST --queries evals/corpus-$WHICH.jsonl"
