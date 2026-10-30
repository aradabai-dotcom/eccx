#!/usr/bin/env python3
"""Build a throwaway corpus, route over it, evaluate over it — through the CLI.

Unit tests cover the pieces; this covers the wiring, which is where every
defect of this session lived: a parameter that is parsed and dropped, a command
that reads the wrong index, a writer that targets a path nobody redefined.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ECCX = ROOT / "eccx"


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    root = tmp / "notes"
    (root / "projets").mkdir(parents=True)
    (root / "projets" / "latence.md").write_text(
        "# Latence de la base\n\nLes requetes lentes viennent des index manquants.\n\n"
        "## Symptome\n\nLe dashboard met quatre secondes a s'afficher.\n")
    (root / "projets" / "vpn.md").write_text(
        "# VPN du bureau\n\n## Coupures\n\nLe tunnel tombe chaque nuit vers trois heures.\n")
    (root / "courses.md").write_text("liste de courses. pain, cafe.\n")
    (root / "q.jsonl").write_text(json.dumps(
        {"q": "le tunnel tombe chaque nuit", "expect": ["projets/vpn"]}) + "\n")

    def cli(*args):
        return subprocess.run([sys.executable, str(ECCX), *args],
                              capture_output=True, text=True, cwd=ROOT)

    r = cli("corpus", "build", "--dir", str(root))
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        return 1
    r = cli("--corpus", str(root), "recall", "le tunnel tombe chaque nuit",
            "--k", "2", "--json")
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        return 1
    ids = [c["id"] for c in json.loads(r.stdout)["candidates"]]
    if ids[:1] != ["projets/vpn"]:
        print(f"FAIL recall returned {ids}", file=sys.stderr)
        return 1
    if any(i.startswith("skill:") for i in ids):
        print(f"FAIL ECC ids leaked into a corpus run: {ids}", file=sys.stderr)
        return 1
    r = cli("--corpus", str(root), "eval", "--file", str(root / "q.jsonl"),
            "--k", "2", "--json")
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        return 1
    m = json.loads(r.stdout)
    if m["recall@1"] != 1.0:
        print(f"FAIL eval over the corpus: {m}", file=sys.stderr)
        return 1
    print(f"  ok  {len(ids)} candidates, eval@1 = {m['recall@1']:.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
