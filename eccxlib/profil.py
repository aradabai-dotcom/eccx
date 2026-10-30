"""Profils de catalogue : quel sous-ensemble de la base on charge.

Un profil est un **choix déclaré**, versionné dans le dépôt, et réversible. Ce
n'est pas une suppression : les fichiers restent, l'index change.

Pourquoi un profil plutôt qu'un élagage : mesuré sur 60 requêtes aveugles,
supprimer 90 skills hors génie logiciel vaut +2 points au rang 1 (19 → 21) et
ne change pas le rappel. Ça ne justifie pas de détruire du contenu qu'on peut
vouloir dans six mois. Le profil donne le même effet, et `--profil` se retire
d'un mot.

Format (profils/<nom>@<version>.json) :

    {
      "id": "logiciel@1",
      "description": "...",
      "source": "vendor/ecc @ <commit>",
      "keep_kinds": ["skill", "agent", "command", "rule", "manual"],
      "exclude": ["nom-de-skill", ...],
      "rationale": "pourquoi ces exclusions"
    }
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "profils"


class ProfileError(RuntimeError):
    pass


def available() -> list[str]:
    if not PROFILES.is_dir():
        return []
    return sorted(p.stem for p in PROFILES.glob("*.json"))


def load(name: str) -> dict:
    """Load a profile by name. `logiciel` and `logiciel@1` are the same thing."""
    if not name:
        raise ProfileError("nom de profil vide")
    path = PROFILES / f"{name}.json"
    if not path.is_file():
        # allow `logiciel` to resolve to `logiciel@1` when only one version exists
        candidates = [p for p in PROFILES.glob("*.json") if p.stem.split("@")[0] == name]
        if len(candidates) != 1:
            known = ", ".join(available()) or "aucun"
            raise ProfileError(f"profil inconnu : {name} (disponibles : {known})")
        path = candidates[0]
    data = json.loads(path.read_text())
    for key in ("id", "exclude"):
        if key not in data:
            raise ProfileError(f"{path.name} : clé « {key} » absente")
    # Exclusions are QUALIFIED (`kind:id`), never a bare id. Three ids in this
    # catalogue exist as both a skill and a command (ecc-guide, marketing-campaign,
    # skill-host-compat); excluding by bare id silently removed the commands too,
    # which the first version of this module did — 93 documents dropped where the
    # profile said 90.
    bad = [e for e in data["exclude"] if not re.fullmatch(r"(?:skill|agent|command|rule|manual):.+", e)]
    if bad:
        raise ProfileError(f"{path.name} : exclusions non qualifiées {bad[:3]} — attendu `kind:id`")
    return data


def apply(index: dict, profile: dict) -> dict:
    """Return a filtered copy of the index. Never mutates the input."""
    drop = set(profile.get("exclude") or [])
    keep_kinds = set(profile.get("keep_kinds") or [])
    docs = [d for d in index["docs"]
            if f"{d['kind']}:{d['id']}" not in drop
            and (not keep_kinds or d["kind"] in keep_kinds)]
    out = dict(index)
    out["docs"] = docs
    out["profil"] = profile["id"]
    return out


def describe(index: dict, profile: dict) -> dict:
    drop = set(profile.get("exclude") or [])
    present = {f"{d['kind']}:{d['id']}" for d in index["docs"]}
    missing = sorted(drop - present)
    return {
        "profil": profile["id"],
        "documents_totaux": len(index["docs"]),
        "exclus_demandes": len(drop),
        "exclus_absents_du_catalogue": missing,   # a stale name is a silent no-op
        "documents_apres": len(index["docs"]) - len(drop & present),
    }
