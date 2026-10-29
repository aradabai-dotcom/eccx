# Votre corpus, mesuré

Ce document existe parce que les deux mesures précédentes portaient sur des
corpus de contrôle (FastAPI, pydantic). Un routeur qui ne gagne que sur
pydantic ne vaut rien pour vous. Celui-ci vient de
`aradabai-dotcom/restaurant-suite`, cloné à froid, sans retouche.

**60 requêtes ont été écrites avant toute mesure** (`evals/corpus-restaurant-suite.jsonl`,
fichier horodaté 22:41, vecteurs calculés à 22:47). Les cibles ont été choisies
en lisant l'arborescence, jamais en regardant ce que l'outil répondait.

## Le corpus

| | |
|---|---|
| documents indexés | 59 (53 `.md`, 6 `.txt`) |
| sections | 382 |
| tokens | 187 603 |
| sections par document | 6,5 (médiane 1 428 tokens) |
| documents sans titre | 6 / 59 — les six `docs/audits/*` |

## Les chiffres

| armée | @1 | @3 | @5 | @20 |
|---|---|---|---|---|
| **lexical** (zéro modèle) | **66,7 %** [54;77] | **78,3 %** [66;87] | 81,7 % | **95,0 %** [86;98] |
| +sémantique | 63,3 % [51;74] | 76,7 % [65;86] | 80,0 % | 96,7 % |
| +sections (mode livré) | 65,0 % [52;76] | 78,3 % [66;87] | 83,3 % | 93,3 % |

Tests appariés contre le lexical, 60 paires :

| armée | profondeur | gains | pertes | p |
|---|---|---|---|---|
| +sémantique | @1 | 1 | 3 | 0,6250 |
| +sémantique | @3 | 1 | 2 | 1,0000 |
| +sections | @1 | 1 | 2 | 1,0000 |
| +sections | @3 | 2 | 2 | 1,0000 |
| +sections | @20 | 0 | 1 | 1,0000 |

Traduction : **ajouter les embeddings ne fait pas mieux, et fait légèrement
moins bien en @1.** C'est la troisième mesure indépendante qui dit la même
chose (ECC : +6,7 @1 ; FastAPI : −5 pts @1 pour le sémantique seul, p=1,000 ;
pydantic : +3,4 @1, p=0,50). Sur un corpus que je n'ai pas choisi, la
conclusion ne bouge pas.

## Le juge de paix : `grep`

C'est la comparaison qui manquait aux deux autres rapports, et l'absence était
une faute — un routeur comparé à « rien » gagne toujours. `grep` est gratuit,
déjà installé, et c'est ce que vous faites aujourd'hui pour retrouver un
document.

| | @1 | @3 | @5 | @20 |
|---|---|---|---|---|
| `grep` brut (somme des occurrences, mots vides retirés) | 5/60 (8,3 %) | 16/60 (26,7 %) | 26/60 (43,3 %) | 44/60 (73,3 %) |

| contre le lexical | routeur mieux | grep mieux | p |
|---|---|---|---|
| @1 | 36 | 1 | < 0,0001 |
| @3 | 34 | 3 | < 0,0001 |
| @5 | 26 | 3 | < 0,0001 |
| @20 | 15 | 2 | 0,0023 |

**+58 points en @1, +52 en @3, toutes deux significatives.** Le routeur ne bat
pas « rien » : il bat `grep`, ce qui est la seule affirmation qui vous concerne.
Les quatre autres affirmations de ce document pèsent moins que celle-ci.

Deux précautions, pour que ce chiffre ne soit pas un procès d'intention inversé :

- Le `grep` de référence lit **exactement** les mêmes fichiers que l'index
  (`.md`, `.markdown`, `.mdx`, `.txt`). Lui donner tout le dépôt (PHP, JSON)
  gonflerait son score et la comparaison porterait sur deux produits différents.
- Son classement est volontairement naïf : somme des occurrences, sans
  stemming, sans idf, sans pondération de champ. Ce sont précisément les
  briques que le routeur ajoute ; les offrir aussi à la référence serait
  mesurer le routeur contre sa propre copie.

## Ce que les échecs disent

Sur les 21 requêtes où le mode livré n'est pas au rang 1, la concentration est
plus instructive que le taux — j'ai compté qui gagne à la place :

| ce qui capte la requête | requêtes |
|---|---|
| `docs/reports/theme-v0.1-reference-integration` (long rapport sur le thème) | **5** |
| l'outillage : `cdc-v3/tooling/CDC-00-outillage-local` (3) et `audit-outils-complementaires-restaurant-suite` (2) | **5** |
| `docs/architecture/revue-senior-cdc-restaurant-suite` | 2 |
| les six `docs/audits/*` (sans titre) | 3 |
| le reste (docs de phase, roadmap, README) | 6 |

Quatre causes, dans l'ordre d'importance :

1. **Un rapport long absorbe le vocabulaire du thème.** Cinq requêtes sur le
   thème (`hooks`, `fonctions principales`, `fonctionnalités`, `aperçu direct`,
   `perf/SEO`) tombent toutes dans le même document. Le mécanisme est précis et
   vaut d'être nommé : le routeur ne compte pas les occurrences — c'est `grep`
   qui fait ça — il compte les **termes de la requête couverts**, pondérés par
   leur rareté. Un rapport long finit par contenir tous ces termes ; sa
   couverture est donc meilleure que celle du document court qui contient
   exactement les bons. Il n'y a volontairement **aucun malus de longueur**, et
   ces cinq échecs sont le prix de ce choix. Le classement par sections est là
   pour rattraper ça ; sur ce corpus il ne le rattrape pas.
2. **Votre dépôt contient des doublons, et le banc les compte comme des
   fautes.** `CDC-00-outillage-local` existe à deux chemins. Sur « comment
   séparer local, staging et production », l'outil a désigné l'autre copie — la
   bonne réponse, au mauvais chemin. Un humain compte ça comme réussi ; le banc
   comme un échec. C'est un défaut de mesure, pas de routage, et il ne se
   corrige pas dans le code. Les deux autres requêtes d'outillage tombent sur
   `audit-outils-complementaires`, un document voisin qui parle des mêmes outils
   — là, c'est un vrai échec.
3. **Les six audits sans titre sont à moitié intouchables** : 3 sur 6 échouent,
   exactement le même mécanisme que pydantic (43/91 sans titre). Un `.txt` sans
   `# Titre` ne peut pas être atteint par un score de section.
4. **Les `expect` multiples rendent certains « échecs » défendables.**
   `order-status-contract` + `permissions-matrix`, ou les trois documents de la
   requête sur la duplication : désigner l'un des trois est une bonne réponse.
   Le banc n'en accepte qu'une liste figée. Sur 60 requêtes, ce biais joue
   contre l'outil, jamais pour lui.

## La décision

Le critère d'arrêt était : **+5 points @3, sinon publier tel quel.** Ils ne
sont pas là — le sémantique et les sections ne gagnent rien, et coûtent 130 Mo
plus 56 secondes d'embeddings. Donc :

- **Le mode par défaut reste lexical** (`eccx recall "…"` sans `--semantic`).
  Il est à 78,3 % @3 sur votre corpus, sans modèle, sans téléchargement.
- `--semantic` reste disponible, non recommandé, et sait maintenant qu'il n'a
  pas de gain mesuré à montrer.
- Le chiffre à retenir est celui-ci : **78,3 % @3, 95 % @20, contre 26,7 % et
  73,3 % pour `grep`.**

## Reproduire

```bash
git clone --depth 1 https://github.com/aradabai-dotcom/restaurant-suite /tmp/rs
./eccx corpus build --dir /tmp/rs
python3 tools/corpus_report.py --corpus /tmp/rs \
    --queries evals/corpus-restaurant-suite.jsonl --k 20 \
    --out rapport.md --json rangs.json
python3 tools/grep_baseline.py --corpus /tmp/rs \
    --queries evals/corpus-restaurant-suite.jsonl --against rangs.json
```

Le second outil est nouveau : il prend le fichier de rangs produit par le
premier, refuse la comparaison si les requêtes ne sont pas les mêmes, et imprime
le test apparié. Sans `--against` il ne mesure que `grep` — il n'y a alors
aucune affirmation à en tirer.
