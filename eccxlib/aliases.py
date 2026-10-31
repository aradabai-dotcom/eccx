"""Alias overlay : donner à un document les mots que l'utilisateur tape vraiment.

Le défaut mesuré
----------------
`latency-critical-systems` décrit le suivi de p50/p95/p99, des caches et des
chemins critiques. Il ne contient nulle part le mot « endpoint » — vérifié : zéro
occurrence dans tout le fichier. Une question comme « cet endpoint met 4 secondes
et la base dit que la requête est bonne » ne peut donc pas l'atteindre, quel que
soit le réglage de poids. C'est un trou de vocabulaire, pas un problème de
classement : la correction est d'ajouter du vocabulaire au document, pas de mieux
ordonner.

Pourquoi un registre, et pas un champ dans les 604 fichiers
-----------------------------------------------------------
`vendor/ecc/` est une base vendue, versionnée par empreinte (`BASE.sha256`) et
resynchronisable (`tools/sync_upstream.sh`). Écrire `aliases:` dans les 604
fichiers de l'amont produirait un diff de 604 fichiers illisible en revue, et
perdu à la première resynchronisation. Le champ existe quand même — il est lu
depuis le frontmatter quand on possède le fichier (`skills-local/`, ou une
fourche) — et le registre `aliases/catalogue.json` couvre ce qu'on ne possède
pas. Une seule représentation en mémoire : `doc["aliases"]`.

Ce que ce n'est pas
-------------------
Ce n'est **pas** une expansion automatique : rien n'est deviné. Chaque entrée est
écrite par un humain, avec sa justification (`why`), et doit répondre à une seule
question : *comment un développeur appellerait-il ce que cette fiche décrit, en
dehors du vocabulaire de la fiche ?*

C'est une **prise de position de contenu**, au même titre qu'un profil de
catalogue : ça se mesure, et ça se relit. Voir `docs/ALIASES.md`.
"""
from __future__ import annotations

import json
from pathlib import Path

from .util import ADAPTER_ROOT

REGISTRY = ADAPTER_ROOT / "aliases" / "catalogue.json"
MAX_TERMS = 12          # a document with 40 aliases is a document with no aliases
MAX_TERM_LEN = 40


class AliasError(ValueError):
    """Registre invalide. Échoue au chargement, jamais silencieusement à l'usage."""


def _clean_terms(raw) -> list[str]:
    if not isinstance(raw, list):
        raise AliasError(f"« terms » doit être une liste, reçu {type(raw).__name__}")
    out: list[str] = []
    for term in raw:
        if not isinstance(term, str):
            raise AliasError(f"terme non textuel : {term!r}")
        term = " ".join(term.lower().split())
        if not term:
            continue
        if len(term) > MAX_TERM_LEN:
            raise AliasError(f"terme trop long ({len(term)} car.) : {term!r}")
        if term not in out:
            out.append(term)
    if len(out) > MAX_TERMS:
        raise AliasError(f"{len(out)} termes pour une fiche, maximum {MAX_TERMS}")
    return out


def load(path: Path | None = None) -> dict[str, list[str]]:
    """Charge le registre. Un fichier absent est un registre vide, pas une erreur.

    Un dépôt où personne n'a encore écrit d'alias doit fonctionner exactement
    comme avant : l'overlay est optionnel par construction.
    """
    path = path or REGISTRY
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AliasError(f"{path} : JSON invalide ({exc})") from exc

    entries = data.get("entries", data)
    if not isinstance(entries, dict):
        raise AliasError(f"{path} : « entries » doit être un objet")

    table: dict[str, list[str]] = {}
    for key, entry in entries.items():
        if key.startswith("_"):          # clés de commentaire
            continue
        if ":" not in key:
            raise AliasError(f"clé {key!r} : attendu « kind:id »")
        if not isinstance(entry, dict):
            raise AliasError(f"{key} : entrée attendue sous forme d'objet")
        why = (entry.get("why") or "").strip()
        if not why:
            raise AliasError(f"{key} : « why » obligatoire — un alias sans "
                             "justification est un ajustement sur la réponse")
        terms = _clean_terms(entry.get("terms") or [])
        if terms:
            table[key] = terms
    return table


def from_frontmatter(meta: dict[str, str]) -> list[str]:
    """Lit `aliases:` dans un frontmatter plat.

    Le parseur du dépôt renvoie des chaînes brutes : on accepte donc
    `aliases: a, b` comme `aliases: [a, b]`.
    """
    raw = (meta.get("aliases") or "").strip()
    if not raw:
        return []
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [t for t in (p.strip().strip("'\"") for p in raw.split(",")) if t]


FM_KEY = "aliases_fm"     # the file's own claim, persisted with the document


def apply(docs: list[dict], table: dict[str, list[str]] | None = None) -> int:
    """Recalcule `doc["aliases"]` = registre + frontmatter. Rend le nombre enrichi.

    **Recalcule, n'accumule jamais.** La première version fusionnait avec la
    valeur déjà présente dans le document, ce qui faisait survivre indéfiniment
    un alias retiré du registre : l'index construit avant le retrait gardait le
    terme, et rien ne le signalait. Deux tests de ce dépôt se contredisaient sur
    ce point, et celui qui avait raison était le plus sévère.

    D'où la séparation : `aliases_fm` porte la revendication du fichier (persistée
    avec lui), `aliases` est toujours recalculé. Un index périmé ne peut donc pas
    mentir sur ce que le registre dit aujourd'hui.
    """
    table = load() if table is None else table
    touched = 0
    for doc in docs:
        key = f"{doc['kind']}:{doc['id']}"
        from_file = list(doc.get(FM_KEY) or [])
        merged = list(dict.fromkeys(list(table.get(key) or []) + from_file))
        if merged:
            touched += 1
        doc["aliases"] = merged
    return touched


def audit(docs: list[dict], table: dict[str, list[str]] | None = None) -> list[str]:
    """Problèmes d'un registre confronté aux documents réels. Liste vide = sain.

    Trois contrôles, chacun pour une erreur déjà commise dans ce dépôt :

    * **identifiant inconnu** — un alias qui ne vise aucun document est mort, et
      il fait croire à une couverture qui n'existe pas ;
    * **alias sans effet** — si tous ses tokens sont déjà dans le nom, la
      description ou les titres, il n'ajoute rien au rappel (le lexique avait
      22 entrées de ce genre) ;
    * **alias vide après tokenisation** — un terme composé uniquement de mots
      vides ne produit aucun token.
    """
    from .util import tokenize

    by_key = {f"{d['kind']}:{d['id']}": d for d in docs}
    problems: list[str] = []
    for key, terms in (table or load()).items():
        doc = by_key.get(key)
        if doc is None:
            problems.append(f"{key} : document inconnu")
            continue
        existing = set(tokenize(doc.get("name", "").replace("-", " ").replace("_", " ")))
        existing |= set(tokenize(doc.get("desc") or ""))
        existing |= set(tokenize(" ".join(doc.get("headings") or [])))
        for term in terms:
            tokens = tokenize(term)
            if not tokens:
                problems.append(f"{key} : « {term} » ne produit aucun token")
            elif not set(tokens) - existing:
                problems.append(f"{key} : « {term} » est déjà dans la fiche (aucun effet)")
    return problems
