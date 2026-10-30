#!/usr/bin/env python3
"""Quels fichiers de la base diffèrent de l'amont, et est-ce voulu ?

`vendor/ecc/` est une copie de l'amont, puis **votre** base : vous la modifiez,
l'amputez, l'étendez. Ce script répond à la seule question qui reste utile
ensuite : *qu'est-ce qui a changé par rapport à ce qu'on a copié ?*

La référence est `vendor/ecc/BASE.sha256`, l'empreinte de chaque fichier au
moment de la copie (commit 25278e7). Trois catégories :

  modifiés   — le fichier existe encore, le contenu a changé
  supprimés  — vous l'avez retiré
  ajoutés    — il n'existait pas dans la base

Sortie informative par défaut ; `--check` renvoie 1 s'il y a du **non commité**
dans `vendor/ecc/` (une modification accidentelle doit être vue, une
modification commitée est par définition un choix).

Usage :
    python3 tools/base_diff.py               # résumé
    python3 tools/base_diff.py --list        # chaque fichier
    python3 tools/base_diff.py --check       # échoue si des changements ne sont pas commités
    python3 tools/base_diff.py --stamp       # régénère BASE.sha256 (après une coupe volontaire)
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "vendor" / "ecc"
STAMP = BASE / "BASE.sha256"
SKIP = {"node_modules", "__pycache__", ".git"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def walk() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(BASE.rglob("*")):
        if not p.is_file() or any(part in SKIP for part in p.parts):
            continue
        if p.name == "BASE.sha256":
            continue
        out[str(p.relative_to(BASE))] = digest(p)
    return out


def read_stamp() -> dict[str, str]:
    if not STAMP.is_file():
        sys.exit(f"manifeste absent : {STAMP.relative_to(ROOT)} — lancer --stamp")
    out = {}
    for line in STAMP.read_text().splitlines():
        if line.strip():
            sha, path = line.split(None, 1)
            out[path.strip()] = sha
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="afficher chaque fichier")
    ap.add_argument("--check", action="store_true", help="échouer si non commité")
    ap.add_argument("--stamp", action="store_true", help="régénérer le manifeste")
    args = ap.parse_args()

    current = walk()

    if args.stamp:
        body = "".join(f"{sha}  {path}\n" for path, sha in sorted(current.items()))
        STAMP.write_text(body)
        print(f"manifeste réécrit : {len(current)} fichiers")
        return 0

    base = read_stamp()
    modified = sorted(p for p in base.keys() & current.keys() if base[p] != current[p])
    removed = sorted(base.keys() - current.keys())
    added = sorted(current.keys() - base.keys())

    print(f"base {len(base)} fichiers · actuelle {len(current)}")
    print(f"  modifiés  {len(modified)}")
    print(f"  supprimés {len(removed)}")
    print(f"  ajoutés   {len(added)}")
    if args.list:
        for label, items in (("modifié", modified), ("supprimé", removed), ("ajouté", added)):
            for p in items:
                print(f"    {label:9s} {p}")
    elif modified or removed or added:
        for label, items in (("modifiés", modified), ("supprimés", removed), ("ajoutés", added)):
            if items:
                preview = ", ".join(items[:5]) + (" …" if len(items) > 5 else "")
                print(f"  {label:9s} {preview}")

    if args.check:
        r = subprocess.run(["git", "status", "--porcelain", "--", "vendor/ecc"],
                           capture_output=True, text=True, cwd=ROOT)
        dirty = [ln for ln in r.stdout.splitlines() if "node_modules" not in ln]
        if dirty:
            print("\nECHEC : changements non commités dans vendor/ecc —", file=sys.stderr)
            for ln in dirty[:10]:
                print(f"   {ln}", file=sys.stderr)
            print("  Une modification de la base doit être un commit qu'on peut lire.",
                  file=sys.stderr)
            return 1
        print("aucun changement non commité dans vendor/ecc")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
