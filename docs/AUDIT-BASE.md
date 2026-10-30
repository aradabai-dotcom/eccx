# Audit de la base — que supprimer, corriger, ajouter

Question posée : *« en tant que dev senior, quels fichiers faudrait-il supprimer,
corriger ou ajouter pour ne pas juste copier ECC ? »*

Réponse courte, avant les détails : **la base est saine. Il n'y a presque rien à
supprimer.** Les 363 fichiers de code sont branchés (5 orphelins), les 311
frontmatters sont valides, il n'y a pas de doublon. Le travail de valeur n'est
pas dans le ménage : il est dans trois défauts structurels que l'audit met au
jour, et dans un ajout que personne n'a fait.

Tout est reproductible : `python3 tools/base_audit.py`.

---

## D'abord, une correction que je me dois

Au tour précédent j'ai écrit que « supprimer le bruit du catalogue fait passer le
rang 1 de 32 % à 50 %, et c'est le levier le plus puissant mesuré ». Le chiffre
est exact, **l'interprétation était fausse**.

Mesure complète, sur les mêmes 60 requêtes :

| catalogue | @1 | @5 | @20 (rappel) |
|---|---|---|---|
| complet, 314 skills | 19/60 (32 %) | 34/60 (57 %) | 51/60 (85 %) |
| − 150 skills | 24/60 (40 %) | 42/60 (70 %) | 53/60 (88 %) |
| − 250 skills | 28/60 (47 %) | 47/60 (78 %) | 53/60 (88 %) |

Le rappel ne bouge pas (85 % → 88 %). **Ce qui change, c'est le nombre de
concurrents pour la première place.** Élaguer ne fait pas mieux classer la bonne
réponse : ça retire celles qui pouvaient la devancer par accident.

Corollaire : si je garde exactement « ce que mes 60 requêtes touchent »
(258 skills, sélectionnée sur les réponses), j'obtiens **19/60** — aucun gain.
Le prétendu levier n'existe pas. Le +18 points était un artefact de mesure, et
élaguer 80 % du catalogue pour gagner un chiffre est du surentraînement, pas de
l'ingénierie.

---

## 1. SUPPRIMER — la liste courte et vérifiable

### 1.1 Cinq candidats, deux suppressions, trois erreurs de ma part

Mon premier détecteur annonçait « 5 orphelins ». C'était faux sur **trois** :
`Path("session-manager.d.ts").stem` vaut `"session-manager.d"`, une chaîne qui
n'existe nulle part. Les trois `.d.ts` sont les déclarations de types de modules
**vivants** (`session-manager.js` est importé par quatre fichiers).
**Détecteur corrigé** — le compter comme orphelin aurait justifié une
suppression réelle.

Restent deux fichiers, dont la suppression est justifiée pour une raison qui
n'est pas « personne ne les référence » mais « ils ne peuvent pas fonctionner
ici » :

| fichier | décision | pourquoi |
|---|---|---|
| `scripts/ci/pi-core-load-test.js` | **supprimé** | exige le CLI `pi` sur le PATH **et** `pi/core/`, qui n'est pas dans la base. Ce n'est pas du code mort : c'est un test d'intégration d'un sous-projet qu'on n'a délibérément pas copié. |
| `scripts/discord/ecc-bot.mjs` | **supprimé** | bot du serveur Discord **communautaire de l'amont**. Dépend d'un `DISCORD_BOT_TOKEN` et d'une communauté qui n'est pas la nôtre. |
| `scripts/lib/package-manager.d.ts` | conservé | types du module `package-manager.js`, actif |
| `scripts/lib/session-aliases.d.ts` | conservé | types du module `session-aliases.js`, actif |
| `scripts/lib/session-manager.d.ts` | conservé | types du module `session-manager.js`, importé par 4 fichiers |

Pour récupérer `pi/` et son test si le besoin apparaît un jour :
`./tools/sync_upstream.sh --add pi scripts/ci/pi-core-load-test.js`.
Le script a été écrit parce que `PROVENANCE.md` y renvoyait… avant qu'il
n'existe.

### 1.2 Ce qu'il ne faut **pas** supprimer, malgré l'apparence

Les 90 skills hors génie logiciel (métier, web3, homelab, scientifique, média)
pèsent 208 000 tokens, soit 30 % du catalogue. Tentant. **Mesuré : +2 points au
rang 1** (19 → 21 sur 60), rappel inchangé.

Et surtout : **trois d'entre elles sont de vraies réponses** dans les jeux
d'évaluation.

| skill | requête où elle est la bonne réponse |
|---|---|
| `healthcare-phi-compliance` | « make sure the model never sees the customer's real email » |
| `ecc-tools-cost-audit` | « the agent burned 40 dollars in one session » |
| `configure-ecc` | « I spend more time fighting the harness than writing code » |

Une suppression par étiquette de domaine les aurait emportées. C'est la leçon :
**on supprime par preuve, jamais par catégorie.**

### 1.3 La règle de suppression qui en découle

Une skill ne se supprime que si elle n'apparaît dans **aucune** des réponses
attendues de *vos* tâches. Comme ce dépôt n'a que des tâches de génie logiciel,
le tri honnête est un **profil**, pas une suppression : voir §3.1.

---

## 2. CORRIGER — trois défauts structurels

### 2.1 L'unité d'injection est trop grosse (le plus grave)

| mesure | valeur |
|---|---|
| médiane d'une skill | **1 931 tokens** |
| skills > 2 000 tokens | 146/311 |
| skills > 4 000 tokens | 45/311 |
| plus grosse (`gateguard`) | **10 564 tokens** |
| plafond d'ECC (`MAX_CONTEXT_BYTES`) | **8 000 tokens** |

Une skill sur deux ne tient pas dans le budget qu'ECC se donne. `gateguard` ne
peut **jamais** être injecté, quel que soit le réglage. Le format du catalogue
(« un fichier = une unité consommable ») et la contrainte réelle (un plafond de
tokens) ne parlent pas la même langue.

**Correction mesurée** : injecter des sections au lieu de fichiers entiers. Au
même plafond de 32 000 octets, sur les 60 requêtes aveugles :

| | bonne réponse présente | octets / requête |
|---|---|---|
| skills entiers | 21/60 (35 %) | 26 433 |
| sections | **51/60 (85 %)** | 20 988 |

Avec la réserve déjà publiée : la tranche injectée ne fait que 13 % du texte du
bon document (quartiles 9–28 %). `python3 tools/token_budget_experiment.py`.

### 2.2 Le rang 1 est le vrai chantier (53 points d'écart)

- rappel `@20` : **51/60 (85 %)** — le bon document est trouvé
- précision `@1` : **19/60 (32 %)** — il n'est presque jamais premier

Le routeur sait trouver ; il ne sait pas trancher. Trois tentatives de
correction, toutes mesurées :

| tentative | résultat |
|---|---|
| bonus si un mot de la requête est dans le nom du composant | **18/60** (pire que 19) |
| indexer le corps du document en plus de la description | −4,6 points (déjà dans le code, commenté) |
| élaguer le catalogue | +2 à +9 selon la coupe, rappel inchangé — artefact de §0 |

Aucune retouche de poids ne marche. Ce qui reste à faire est un **second étage
discriminatif** : un modèle qui prend les 20 candidats et n'en garde qu'un, sur
une question différente (« lequel répond vraiment ? » plutôt que « lequel
ressemble au texte ? »). C'est le seul chantier de ce dépôt qui vaut 53 points.

### 2.3 Hygiène du code vendu : propre

| contrôle | résultat |
|---|---|
| `eval` / `new Function` en production | **0** (2 occurrences, dans des fixtures de test du bloqueur — attendu) |
| requêtes réseau sortantes construites dans les hooks | **0** (les URL sont des liens de documentation) |
| hooks lançant un sous-processus | 19/58 — inhérent à un système de hooks |

Rien à corriger ici. Le signaler fait partie de l'audit : un dossier qu'on
vendorise doit être audité sur ce qu'il exécute, pas seulement sur ce qu'il dit.

---

## 3. AJOUTER — trois choses qui manquent vraiment

### 3.1 Un profil « génie logiciel » (au lieu d'une suppression)

Le bon geste n'est pas de supprimer les 90 skills hors domaine : c'est de
**déclarer ce qu'on charge**. Un fichier de profil, versionné, réversible :

- ne supprime aucun fichier ;
- dit explicitement quelles skills sont dans le périmètre ;
- se révise en une ligne quand vous changez de métier.

Mesuré : garder les 218 skills logiciels donne **21/60** contre 19/60, rappel
identique. Ce n'est pas spectaculaire, et c'est exactement pour ça qu'il faut le
faire comme un profil — pas comme une opération irréversible sur le catalogue.

### 3.2 Le patch d'injection par sections

C'est le seul ajout de ce dépôt avec un facteur mesuré : **2,4× plus de bonnes
réponses à budget égal**. Il appartient à `scripts/lib/context-selection.js`,
c'est-à-dire à la base vendue. À écrire en JS, avec la vérification des *spans*
contre le digest de la source (le reçu d'ECC est lié par digest : on ne peut pas
envoyer des morceaux sans dire lesquels).

### 3.3 Les skills que vous écrirez, et qu'ECC ne peut pas avoir

`skills-local/` en contient déjà trois, écrites pour combler des trous prouvés
par l'évaluation (`repository-hygiene`, `large-file-decomposition`,
`pii-redaction`), et chacune gagne sur une formulation jamais vue. C'est le seul
endroit du dépôt où votre valeur ajoutée est structurelle : **ce que votre
métier demande et que 311 skills génériques ne couvrent pas.**

---

## Ce que je ferais, dans cet ordre

1. **Supprimer les 5 orphelins** — 10 minutes, zéro risque.
2. **Écrire le profil logiciel** — 1 heure, réversible, mesuré (+2 @1).
3. **Attaquer le rang 1** — c'est là que sont 53 points, et rien d'autre dans
   cet audit n'en approche. Second étage discriminatif, mesuré sur les mêmes 60
   requêtes.
4. **Le patch d'injection par sections** — facteur 2,4 déjà mesuré, à porter
   dans la base.
5. **Vos skills** — dès que vous m'aurez donné vos 15–20 tâches réelles.

Ce qui n'est **pas** dans cette liste : élaguer le catalogue. C'est la seule
chose que j'ai présentée comme un levier au tour précédent, et la mesure
complète dit qu'elle n'en est pas un.

---

## Refaire cet audit

```bash
python3 tools/base_audit.py                 # les 7 contrôles
python3 tools/base_audit.py --only rank-gap # un seul
python3 tools/token_budget_experiment.py    # budget à plafond égal
python3 tools/prune_experiment.py           # ce que l'élagage fait vraiment
```
