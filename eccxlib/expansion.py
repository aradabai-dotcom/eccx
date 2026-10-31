"""Expansion de requête par co-occurrence dans le catalogue.

Le trou de vocabulaire mesuré : `latency-critical-systems` ne contient nulle
part le mot « endpoint ». Aucun réordonnancement ne peut faire gagner un
document qui ne partage **aucun terme** avec la requête — il faut ajouter des
termes, pas mieux classer.

Pourquoi la co-occurrence et pas un thésaurus écrit à la main : un thésaurus
technique rédigé par moi, puis mesuré sur mes propres jeux, serait de
l'ajustement sur la réponse. Ici les associations viennent des 604 documents du
catalogue : si « endpoint » et « api » apparaissent ensemble dans beaucoup de
fiches, c'est une propriété du corpus, pas une intuition, et elle se recalcule
à chaque `eccx index`.

Précautions, chacune pour une raison mesurée :

* **PMI, pas fréquence brute.** Les mots fréquents co-occurrent avec tout ; le
  pointwise mutual information les élimine naturellement.
* **Seuil de co-occurrence** (3 documents) : une paire vue une seule fois est
  une anecdote.
* **Poids faible** (0.30) : une expansion propose, elle ne décide pas. Les
  termes de la requête gardent 1.0, les synonymes déclarés 0.55.
* **Jamais un terme déjà présent** dans la requête, jamais un mot vide.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from .util import STOP, tokenize

MIN_DOCS = 3          # below this, a co-occurrence is an anecdote
MIN_PMI = 1.2         # ~3.3x more likely together than by chance
MAX_EXPANSIONS = 3    # per query term
WEIGHT = 0.30         # proposed, never decisive


def _doc_terms(doc: dict) -> set[str]:
    """The vocabulary a document is *about*, not its whole body."""
    parts = [doc.get("name", "").replace("-", " ").replace("_", " "),
             doc.get("desc") or "",
             " ".join(doc.get("headings") or [])]
    return {t for t in tokenize(" ".join(parts)) if t not in STOP and len(t) > 2}


def build(index: dict) -> dict[str, list[tuple[str, float]]]:
    """Return {term: [(associated_term, pmi), ...]} built from the catalogue."""
    docs = [_doc_terms(d) for d in index["docs"]]
    n = len(docs)
    if n < 10:
        return {}

    term_docs: Counter[str] = Counter()
    pair_docs: Counter[tuple[str, str]] = Counter()
    for terms in docs:
        for t in terms:
            term_docs[t] += 1
        ordered = sorted(terms)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                pair_docs[(a, b)] += 1

    assoc: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (a, b), count in pair_docs.items():
        if count < MIN_DOCS:
            continue
        pmi = math.log((count / n) / ((term_docs[a] / n) * (term_docs[b] / n)))
        if pmi < MIN_PMI:
            continue
        assoc[a].append((b, pmi))
        assoc[b].append((a, pmi))

    out: dict[str, list[tuple[str, float]]] = {}
    for term, neighbours in assoc.items():
        neighbours.sort(key=lambda kv: -kv[1])
        out[term] = neighbours[:MAX_EXPANSIONS]
    return out


def expand(tokens: list[str], table: dict[str, list[tuple[str, float]]]) -> dict[str, float]:
    """Return extra terms with their weights, excluding anything already asked."""
    present = set(tokens)
    extra: dict[str, float] = {}
    for t in tokens:
        for other, pmi in table.get(t, ()):
            if other in present:
                continue
            # a stronger association earns a slightly stronger weight, bounded
            w = WEIGHT * min(1.0, pmi / 3.0) + 0.08
            extra[other] = max(extra.get(other, 0.0), min(w, 0.45))
    return extra


def explain(term: str, table: dict[str, list[tuple[str, float]]]) -> str:
    """Human-readable view, used by `tools/eval_report.py --explain`."""
    near = table.get(term)
    if not near:
        return f"{term}: aucune association retenue"
    return f"{term} → " + ", ".join(f"{t} (pmi {p:.2f})" for t, p in near)
