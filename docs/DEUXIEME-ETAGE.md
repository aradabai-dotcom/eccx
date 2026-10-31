# Le second étage : cinquante configurations, aucun gain démontrable

Vous avez demandé un étage discriminatif, à construire **après** le lexique et
l'expansion. Le voici : construit, mesuré sur trois jeux, et **laissé optionnel**
parce qu'il ne franchit pas la barre de significativité. Ce document dit
exactement ce qui a été essayé, dans l'ordre, et pourquoi j'ai conclu que ce
n'était pas la peine.

---

## Le diagnostic de départ

Le premier étage (BM25F par champs) trouve mais ne tranche pas : rappel @20 de
85 %, précision @1 de 45 %. L'écart de 40 points est théoriquement récupérable
par un réordonnancement. Trois échecs typiques semblaient de ce genre :

| requête | ce que le routeur renvoie | ce qu'il fallait |
|---|---|---|
| our CI **pipeline** fails intermittently | `opensource-pipeline` | `github-ops` |
| the retry logic double **charges** the customer | `customs-trade-compliance` | `error-handling` |
| this **endpoint** takes 4 seconds | `scientific-db-pubmed-database` | `latency-critical-systems` |

Dans les trois cas, un mot de la requête est dans le *nom* d'un document non
pertinent, et le document pertinent ne partage avec la requête qu'un vocabulaire
plus dispersé. L'hypothèse à tester : un second étage qui compte **combien** de
termes de la requête un document couvre battrait un premier étage qui compte
**où** ils apparaissent.

## Ce qui a été essayé

Les mesures portent sur 80 requêtes : les 20 tâches senior, `heldout` (30) et
`heldout2` (30). Toutes les variantes sont évaluées deux fois : une fois pour le
choix, une fois pour vérifier qu'il ne défait pas ce que le premier étage avait
réussi.

### Bloc 1 — l'étendue lexicale (36 configurations)

| signal ajouté au score | formes testées | résultat |
|---|---|---|
| couverture de la requête, uniforme | additif, alpha 0,2 → 2,0, fenêtres 5/10/20 | neutre à −1 |
| couverture de la requête, pondérée idf | idem | neutre à −1 |
| pénalité « termes partagés seulement via le nom » | beta 0 → 0,8 | **jamais déclenchée** |
| pénalité « nom mal expliqué » par la requête | alpha 0,2 → 1,0 | −1 à −2 |
| bonus « description bien expliquée » | alpha 0,2 → 1,0 | neutre |

Deux découvertes pendant ce bloc, toutes deux instructives :

1. **La pénalité « nom seul » ne se déclenche jamais** — 0 fois sur 400
   candidats. Les descriptions contiennent aussi ces mots : un document nommé
   `customs-trade-compliance` parle de « charges » dans son texte. Le signal
   était une hypothèse fausse sur les données.
2. **La normalisation détruisait l'information.** Diviser le score par celui du
   meilleur ramenait 14,8 et 13,5 à 1,00 et 0,91, et un terme d'étendue de 0,5
   décidait alors à lui seul — l'étage 2 renversait l'étage 1 qu'il devait
   affiner. En passant à une perturbation multiplicative bornée, le problème a
   disparu sans que le gain apparaisse.

### Bloc 2 — le poids du nom

L'hypothèse « le nom est surpondéré » se teste directement :

| poids du nom | 20 tâches senior | heldout | heldout2 |
|---|---|---|---|
| 5,0 (actuel) | **9 / 11** | **11 / 15** | **8 / 15** |
| 4,0 | 8 / 11 | 11 / 15 | 7 / 15 |
| 3,0 | 8 / 10 | 11 / 15 | 7 / 12 |

5,0 est déjà l'optimum. **Le nom ne domine pas parce qu'il est trop lourd, mais
parce qu'il est un bon signal.** La piste est close.

### Bloc 3 — l'étage sémantique, conditionné

Le seul signal avec un gain documenté ailleurs dans le dépôt
(`docs/ROUTING-GENERALISATION.md`). Il est cher : 273 Mo de modèle, ~8 ms par
requête. D'où la condition : n'escalader **que** si le premier étage hésite,
c'est-à-dire si son top-2 tient dans 20 % du top-1.

Mesuré à fenêtre 20, alpha de fusion de 1 à 5, marge de 0,10 à 0,40 :

Mesuré dans la configuration réellement livrée (expansion désactivée), sur les
80 requêtes des trois jeux réunis :

| configuration | escalades | @1 | @3 | @20 |
|---|---|---|---|---|
| étage 1 seul | — | 28/80 | 41/80 | 67/80 |
| étage 1 + 2 (marge 0,20, alpha 5,0) | 44/80 | **30/80** | **44/80** | 67/80 |
| étage 1 + 2 (marge 0,20, alpha 2,0) | 44/80 | 30/80 | 44/80 | 67/80 |
| étage 1 + 2 (marge 0,40, alpha 5,0) | 61/80 | 30/80 | 46/80 | 67/80 |

Test de McNemar exact, configuration retenue (marge 0,20, alpha 5,0) :

| métrique | victoires | défaites | p |
|---|---|---|---|
| @1 | 5 | 3 | **0,73** |
| @3 | 4 | 1 | **0,38** |
| @20 | 0 | 0 | 1,00 |

Aucune n'est significative. La direction est positive (+2 au rang 1, +3 au rang
3 sur 80 requêtes), mais un p de 0,73 ne permet pas de l'affirmer : c'est ce
qu'un jeu de 80 requêtes produit par hasard. Le classement @20 est identique —
l'étage 2 ne récupère aucun document absent, ce qui confirme que le problème est
le rappel, pas l'ordre.

## Pourquoi ça ne peut pas marcher, en fait

Le plafond du réordonnancement est le rappel : **17/20**. Les trois documents
manquants ne sont pas mal classés, ils sont absents. Et ils sont absents pour une
raison mécanique :

- `github-ops` ne contient aucun des mots de « our CI pipeline fails
  intermittently » ;
- `security-scan` ne contient aucun des mots de « an access key got committed » ;
- `security-review` ne contient aucun mot fort de la question française
  correspondante.

Aucun score, sémantique ou non, ne peut promouvoir un document que la liste de
candidats ne contient pas. L'étage 2 traite un problème qui n'est pas celui des
données.

## Ce qui est livré

`eccxlib/second_stage.py`, disponible via `eccx recall --two-stage`,
**désactivé par défaut**. Onze tests (`tests/test_second_stage.py`), dont un qui
vérifie l'alignement des lignes de matrice — le vrai risque de ce genre de code.

Ce risque mérite d'être nommé : la matrice de vecteurs est construite sur le
catalogue entier. Un document classé n°1 peut être la ligne 57 de la matrice.
Calculer `matrix[0]` pour le premier résultat note chaque document contre le
vecteur d'un autre, **sans lever d'erreur et avec des scores plausibles**. La
première version avait ce défaut ; le test le détecte (vérifié en réintroduisant
le bug volontairement).

## Ce qu'il faudrait pour que l'étage 2 serve à quelque chose

Deux choses, dans cet ordre :

1. **Un rappel proche de 100 %** sur ces tâches — donc un catalogue qui sait dire
   « je parle aussi de pipeline quand je m'appelle github-ops », ou des
   plongements multilingues qui rapprochent « pipeline » de « github-ops » par le
   sens. Alors seulement un réordonnancement aura de quoi travailler.
2. **Un jeu de mesure plus grand.** 80 requêtes ne distinguent pas +5 de 0. À
   300 requêtes, le même effet serait détectable ; à 80, il ne l'est pas, et
   prétendre le contraire serait le défaut que ce dépôt combat.
