# Le protocole, exécuté pour de vrai sur un corpus que je n'ai jamais vu

Le corpus de l'utilisateur n'était pas disponible. Plutôt que d'attendre, la
seule chose honnête à faire était de **livrer l'instrument** et de le prouver
sur un corpus frais. Ce document est le compte rendu brut, y compris quand il
contredit ce que le projet espérait.

## Le corpus

Documentation de **pydantic** (branche `main`), 91 pages markdown, 388 sections,
182 243 tokens. Aucune de ces pages n'a jamais été mesurée, et le catalogue ECC
n'y intervient pas.

**60 requêtes écrites en une passe avant toute mesure** :
`evals/corpus-pydantic.jsonl`, horodaté à 22:14:23. À ce moment-là, l'index
venait d'être construit — donc les titres étaient connus, ce qui est légitime et
nécessaire — mais **aucune requête n'avait été passée au moteur**. Le fichier a
ensuite été corrigé sur un point : une de mes 60 cibles (`api:api/validators`)
n'existait pas dans l'index ; l'outil l'a refusée avant de mesurer, en nommant
l'identifiant fautif.

## Les chiffres

| armée | @1 | @3 | @5 | @20 |
|---|---|---|---|---|
| lexical seul | **43,3 %** [32-56] | **61,7 %** [49-73] | 70,0 % | **85,0 %** [74-92] |
| + sémantique (document) | 46,7 % [35-59] | 66,7 % [54-77] | 76,7 % | 90,0 % [80-95] |
| + sections | 41,7 % [30-54] | 56,7 % [44-68] | 71,7 % | 78,3 % [66-87] |

Tests appariés contre le lexical, McNemar exact :

| armée | @1 | @3 | @20 |
|---|---|---|---|
| + sémantique | 2 gains / 0 perte, p = 0,50 | 4 / 1, p = 0,38 | 3 / 0, p = 0,25 |
| + sections | **7 gains / 8 pertes**, p = 1,00 | 8 / 11, p = 0,65 | **5 / 9, p = 0,42** |

## Ce que ça dit, et qui n'est pas agréable

**1. Les sections n'aident pas ici. Elles nuisent légèrement.** −1,6 point en
@1, −6,7 en @20, sans être significatif. Sur le catalogue ECC, les mêmes
sections valaient +6,7 points @1 avec p = 0,021 sur 149 requêtes aveugles.

L'explication est mécanique, pas mystérieuse : **43 des 91 documents n'ont
aucun titre**. Ce sont les pages de référence API, qui n'utilisent que des
directives mkdocstrings. Le score de section ne peut exister que pour 48
documents sur 91 ; pour les autres il n'ajoute que du bruit de fusion.

**2. Le gain d'ECC venait d'indexer le corps, pas du modèle.** Ici, le corps est
déjà dans le score lexical (champ `sec`, rempli pour tout corpus personnel). Le
modèle n'ajoute plus que 2 requêtes sur 60, non significatif. C'est la même
conclusion que sur FastAPI (+2,5 pts, p = 1,0) : **le modèle n'est pas ce qui
fait marcher la chose**.

**3. Sur un corpus de 91 documents, `@1 = 43 %` est une bonne nouvelle pour
`grep`.** Ma propre règle dit qu'en dessous de ~200 documents, la recherche par
mot-clé gagne. Elle se vérifie : la couche sémantique complète coûte 130 Mo de
modèle et 250 Mo de RAM pour +3,4 points @1 non significatifs.

**4. Ce que l'outil apporte quand même** : `@20 = 85 %` en lexical pur, sans
aucun modèle, sur 91 documents et 182 k tokens. Sur un corpus plus gros — celui
pour lequel il est fait — ce ratio est le seul qui compte.

## La règle qui en sort, et que je m'applique

> Avant de payer 130 Mo de modèle et 9 minutes d'embeddings, mesurer l'armée
> lexicale. Si elle est à moins de 5 points, ne pas payer.

Sur ce corpus, l'écart @1 est de 3,4 points et l'intervalle de confiance le
contient. **La bonne configuration ici est le mode lexical.**

## Ce que ça change pour votre corpus

- **Comptez vos documents sans titre.** Si plus de la moitié n'en ont pas, le
  score de section ne servira à rien et il faut commencer en lexical.
- **Publiez `@20` avant `@1`.** C'est ce que l'outil fait réellement : une
  shortlist, pas une réponse.
- **Ne cherchez pas le modèle.** Mesurez d'abord à zéro coût.

## Troisième passage : votre corpus, et la référence qui manquait

Les deux mesures ci-dessus comparent le routeur à lui-même. C'est insuffisant :
une armée qui bat « rien » ne prouve rien. Sur un troisième corpus — le vrai
projet WordPress, 59 documents, 60 requêtes écrites avant mesure — la même
comparaison a été refaite **contre `grep` brut**, et le résultat est le seul
chiffre de cette page qui vaille comme promesse : 66,7 % @1 et 78,3 % @3 contre
8,3 % et 26,7 % pour `grep` (p < 0,0001 à chaque profondeur). Les embeddings,
eux, n'ajoutent toujours rien : −3,4 points @1, p = 0,625.

Détail, échecs et décision : `docs/CORPUS-RESTAURANT-SUITE.md`.

> Règle ajoutée : **toute mesure de routage inclut désormais `grep` comme
> quatrième colonne.** `tools/grep_baseline.py --against` refuse la comparaison
> si les deux jeux de rangs ne portent pas sur les mêmes requêtes, et lit
> exactement les mêmes suffixes que l'indexeur — ni plus (ce serait offrir au
> concurrent ce que le produit n'a pas le droit de lire), ni moins (c'est le bug
> qui a d'abord perdu six documents).

## Reproduire

```bash
tools/fetch_corpus.sh /tmp/corpus/fastapi-docs     # l'autre corpus de contrôle
./eccx corpus build --dir /tmp/corpus/pydantic
./eccx --corpus /tmp/corpus/pydantic vectors       # 58 s
python3 tools/corpus_report.py --corpus /tmp/corpus/pydantic \
    --queries evals/corpus-pydantic.jsonl --k 20 --out rapport.md
```

`tools/corpus_report.py` est le même instrument pour votre dossier : trois
armées appariées, intervalles de Wilson, McNemar exact, et la liste des échecs
à examiner à la main.
