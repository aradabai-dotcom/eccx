"""Traduction des termes techniques français vers le vocabulaire du catalogue.

Le catalogue ECC est entièrement en anglais ; le routeur n'a aucune capacité
interlingue. Mesuré avant ce module : **0/4** sur des requêtes françaises de dev
senior (« mon déploiement de production a échoué » → `review-pr`).

Principe : on ne traduit pas la phrase, on **ajoute** au texte de la requête les
équivalents anglais des termes techniques rencontrés. Le routeur voit alors les
deux vocabulaires, et les mots français qui ne mènent nulle part deviennent du
bruit inoffensif (ils ne matchent aucun document).

Trois règles de conception, chacune pour éviter un piège mesuré :

1. **On ne traduit que ce qui diffère.** `migration`, `performance`, `service`,
   `incident`, `production`, `documentation`, `version` s'écrivent pareil dans
   les deux langues. Les mapper créerait des doublons qui faussent la couverture
   (`cov`) sans rien apporter.
2. **Les locutions passent avant les mots.** « file d'attente » doit devenir
   `queue`, pas `queue` + `wait`. « revue de code » doit devenir `review` +
   `code`, pas trois mots isolés.
3. **Les accents ne comptent pas.** « déploiement » et « deploiement » sont la
   même entrée : on compare sur la forme déaccentuée.

Le lexique est volontairement un **fichier de données**, pas une heuristique :
il se relit, se conteste et s'étend sans toucher au routeur. C'est aussi ce qui
le rend testable — `tests/test_lexique.py` vérifie qu'aucune entrée ne traduit
un mot vers lui-même.
"""
from __future__ import annotations

import re
import unicodedata

# ── Locutions : appliquées d'abord, sur le texte déaccentué ──────────────────
# Ordre significatif : la plus longue d'abord (voir `_apply_phrases`).
PHRASES: dict[str, str] = {
    "mise en production": "deploy release production",
    "mise en ligne": "deploy release",
    "retour arriere": "rollback revert",
    "revue de code": "code review",
    "revue de securite": "security review",
    "revue par les pairs": "peer review",
    "integration continue": "continuous integration ci",
    "livraison continue": "continuous delivery",
    "deploiement continu": "continuous deployment",
    "file d attente": "queue",
    "file dattente": "queue",
    "base de donnees": "database",
    "fuite de memoire": "memory leak",
    "test unitaire": "unit test",
    "tests unitaires": "unit test",

    "test de bout en bout": "end to end test",
    "lignes de code": "lines of code",
    "mot de passe": "password credential secret",
    "cle d acces": "access key credential",
    "cle api": "api key credential",
    "jeton d acces": "access token",
    "document d architecture": "architecture decision record",
    "decision d architecture": "architecture decision record",
    "liste de controle": "checklist",
    "tableau de bord": "dashboard",
    "plan de reprise": "disaster recovery",
    "sans interruption": "without downtime",
    "sans interrompre le service": "without downtime",
    # Word order is the signal these exist for: the router rewards an adjacent
    # query bigram appearing in a name, and "legacy code" -> "code legacy" is
    # what makes that bigram fire. Same tokens, different ranking.
    "test d integration": "integration test",
    "code legacy": "legacy code",

    "montee de version": "upgrade",
    "gestion des dependances": "dependency management",
    "double facturation": "double charge",
    "facture deux fois": "double charge",
    "bug de production": "production bug incident",
}

# ── Mots isolés : jamais un mot vers lui-même ────────────────────────────────
WORDS: dict[str, str] = {
    # livraison / exploitation
    "deploiement": "deployment deploy",

    "deploie": "deploy",
    "deploye": "deploy",
    "deployes": "deploy",
    "deployee": "deploy",
    "deployees": "deploy",
    "deploiement": "deployment deploy",
    "deploiement": "deployment deploy",

    "livraison": "delivery release",
    "livrer": "ship release",
    "panne": "outage failure incident",
    "panne": "outage failure incident",

    "coupure": "outage downtime",
    "indisponibilite": "outage downtime availability",
    "echec": "failure fail",
    "echoue": "fail failure",
    "echouee": "fail failure",
    "echoues": "fail failure",
    "erreur": "error",
    "erreurs": "error",
    "correctif": "patch fix",
    "correction": "fix patch",

    "anomalie": "bug defect",
    "bogue": "bug",
    "sauvegarde": "backup",
    "sauvegardes": "backup",
    "restauration": "restore recovery",
    "restaurer": "restore",
    "repli": "rollback failover",
    "supervision": "monitoring",
    "surveillance": "monitoring watch",
    "alerte": "alert",
    "alerte": "alert",
    "journal": "log",
    "journalisation": "logging",
    "metrique": "metric",
    "metriques": "metric",
    "astreinte": "on call",
    # versionnage / collaboration
    "revue": "review",
    "relire": "review",
    "relis": "review",
    "relecture": "review",
    "fusion": "merge",
    "fusionner": "merge",
    "fusionne": "merge",
    "fusionnee": "merge",

    "branche": "branch",
    "depot": "repository repo",
    "depots": "repository",
    "pousser": "push",
    "pousse": "pushed push",
    "tirer": "pull",
    "valider": "commit approve",
    "validation": "approval validation",
    "collaborateur": "colleague teammate",
    "collegue": "colleague teammate",
    "equipe": "team",
    # build / tests
    "compilation": "build compile",
    "compiler": "build compile",
    "construire": "build",
    "construis": "build",

    "essai": "test",
    "couverture": "coverage",
    "instable": "flaky unstable",
    "instables": "flaky unstable",
    "intermittent": "intermittent flaky",
    "lent": "slow latency",
    "lente": "slow latency",
    "lenteur": "slow latency performance",
    "lenteurs": "slow latency performance",
    "accelerer": "faster speed optimize",
    "ralentissement": "slowdown latency",
    # données
    "donnees": "data",
    "requete": "query request",
    "requetes": "query request",
    "colonne": "column",
    "ligne": "row line",
    "lignes": "row line",

    "cle": "key",
    "cles": "key",

    "migrer": "migrate migration",

    "volume": "volume size",
    "gigaoctets": "gigabytes size",
    "octets": "bytes size",
    "poids": "size weight",
    "taille": "size",
    "reduire": "reduce shrink",
    "allegement": "slim reduce",
    # sécurité
    "securite": "security",
    "faille": "vulnerability flaw",
    "failles": "vulnerability flaw",
    "vulnerabilite": "vulnerability",

    "jeton": "token",
    "authentification": "authentication auth",
    "autorisation": "authorization auth",
    "chiffrement": "encryption",
    "chiffrer": "encrypt",
    "fuite": "leak",
    "expose": "exposed leak",
    "exposee": "exposed leak",

    "motdepasse": "password",
    "acces": "access",
    # architecture

    "justifier": "justify rationale",
    "justification": "rationale",
    "motif": "pattern",
    "patron": "pattern",
    "norme": "standard",
    "regle": "rule",
    "regles": "rule",
    "qualite": "quality",
    "refactorisation": "refactoring",
    "refactoriser": "refactor",
    "decouper": "decompose split",
    "decoupage": "decomposition",
    "fichier": "file",
    "fichiers": "file",
    "ancien": "legacy old",
    "ancienne": "legacy old",
    "vieux": "legacy old",
    "heritage": "legacy inheritance",
    "reprender": "onboarding take over",
    "reprendre": "onboarding take over",
    "revenir": "revert rollback previous",
    "precedent": "previous revert rollback",
    "precedente": "previous revert rollback",
    "precedents": "previous",
    "retrograder": "downgrade rollback",
    "annuler": "revert rollback undo",
    "comprendre": "understand onboarding",
    # produit / facturation
    "paiement": "payment",
    "paiements": "payment",
    "facturation": "billing invoice",
    "facture": "invoice billing",
    "facturer": "charge bill",
    "debit": "charge",
    "debite": "charged",
    "client": "customer",
    "clients": "customer",
    "commande": "order",
    "commandes": "order",
    "remboursement": "refund",
    "rembourser": "refund",

    "deuxfois": "twice double",
}

_PHRASE_KEYS = sorted(PHRASES, key=len, reverse=True)


def _inflections(word: str) -> set[str]:
    """Formes fléchies plausibles d'une entrée française.

    Un vrai racinisateur français serait plus élégant et plus fragile. Ici on
    génère, à partir de chaque entrée, les formes qu'un développeur tape
    vraiment : « échouer » donne échoue / échouent / échoué / échouée / échoués,
    « fusionner » donne fusionné / fusionnée. Les formes générées sont
    exactement celles que le lexique doit reconnaître, et elles sont visibles
    dans le fichier plutôt qu'enfouies dans une règle.
    """
    forms: set[str] = set()
    if word.endswith("er"):                       # infinitif
        root = word[:-2]
        forms |= {root + e for e in ("e", "es", "ent", "é", "ée", "és", "ées", "ant", "ais", "ait")}
    if word.endswith("e"):                        # participe / présent
        forms |= {word + "s", word + "nt"}
    if word and not word.endswith("s"):
        forms.add(word + "s")                     # pluriel
    return forms


def _build_index() -> dict[str, str]:
    table = dict(WORDS)
    for word, english in WORDS.items():
        for form in _inflections(word):
            table.setdefault(form, english)
    return table


LOOKUP: dict[str, str] = _build_index()


def _fold(text: str) -> str:
    """Lowercase, strip accents, collapse punctuation to single spaces."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _apply_phrases(folded: str) -> tuple[str, list[str]]:
    """Replace known French phrases by their English equivalents.

    Returns the rewritten text and the list of translations applied, so callers
    can report what happened instead of doing it invisibly.
    """
    hits: list[str] = []
    out = folded
    for phrase in _PHRASE_KEYS:
        if phrase in out:
            out = out.replace(phrase, " " + PHRASES[phrase] + " ")
            hits.append(f"{phrase}→{PHRASES[phrase]}")
    return " ".join(out.split()), hits


def rewrite(query: str) -> tuple[str, list[str]]:
    """Return (query + English equivalents, list of translations applied).

    The original words are kept: a French query keeps its own vocabulary, and
    the English terms are *added*. Nothing is removed, so an English query goes
    through untouched.
    """
    if not query or not query.strip():
        return query, []

    folded, hits = _apply_phrases(_fold(query))
    extra: list[str] = []
    for word in folded.split():
        english = LOOKUP.get(word, "")
        if english:
            extra.append(english)

    if not extra and not hits:
        return query, []

    # de-duplicate, keep order, drop words already present in the query
    present = set(folded.split())
    seen: set[str] = set()
    tail: list[str] = []
    for chunk in extra:
        for term in chunk.split():
            if term and term not in present and term not in seen:
                seen.add(term)
                tail.append(term)

    if not tail and not hits:
        return query, hits
    # `folded` carries the phrase replacements; returning `query` here threw them
    # away, so every location in PHRASES was inert. Only adopt it when a phrase
    # actually matched, so an English query is still handed back untouched.
    text = folded if hits else query
    if tail:
        text = text + " " + " ".join(tail)
    return text, hits
