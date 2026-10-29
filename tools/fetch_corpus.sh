#!/usr/bin/env bash
# Fetch the independent validation corpus used in docs/CORPUS.md.
#
# FastAPI's documentation: 156 markdown pages, ~986 sections, written for
# humans by someone who never heard of this project. It exists here for one
# reason — to check that the mechanism measured on the ECC catalogue is a
# property of *retrieval*, not of that catalogue.
#
# Not vendored: third-party content, MIT-licensed but 19 MB of it. Re-fetched
# on demand.
set -euo pipefail

DEST="${1:-/tmp/corpus/fastapi-docs}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "downloading fastapi docs..."
curl -sL -o "$TMP/fa.tgz" https://codeload.github.com/fastapi/fastapi/tar.gz/refs/heads/master
mkdir -p "$DEST"
tar xzf "$TMP/fa.tgz" -C "$TMP" --strip-components=3 fastapi-master/docs/en/docs
cp -r "$TMP/docs/en/docs/." "$DEST/" 2>/dev/null || \
  (mkdir -p "$TMP/x" && tar xzf "$TMP/fa.tgz" -C "$TMP/x" --strip-components=2 \
     fastapi-master/docs/en/docs && cp -r "$TMP/x/docs/en/docs/." "$DEST/")

n=$(find "$DEST" -name "*.md" | wc -l)
echo "$n markdown files in $DEST"
echo
echo "next:"
echo "  ./eccx corpus build --dir $DEST"
echo "  ./eccx --corpus $DEST eval --file evals/corpus-fastapi.jsonl --k 20 --json"
