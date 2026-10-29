# Mutation testing — tri des survivants

Écrit **à la main**. `tools/mutate.sh` régénère `docs/MUTATION.md` (chiffres bruts,
liste des survivants) mais ne touche pas à ce fichier.

Run de référence : **2 639 mutants, 1 914 tués, 463 survivants, 3 timeouts,
259 sans test → 80,4 %** (~21 min, 2,06 mutants/s). Périmètre : `util`,
`rerank`, `evaluate`, `router`, `indexer`.

| périmètre | mutants | score |
|---|---|---|
| util + rerank + evaluate | 1 118 | 72,2 % |
| + router + indexer (avant triage) | 2 421 | 69,0 % |
| + triage du 1er passage | 2 476 | 79,0 % |
| + durabilité, déterminisme, épinglage | 2 505 | 79,3 % |
| + projection `resolve`, `--expand` mesuré, budget au CLI | 2 639 | **80,4 %** |

## Par module

Table du run à **2 505** mutants. Les totaux du run à 2 639 sont
`evaluate` 368, `indexer` 421, `rerank` 576, `router` 914, `util` 360 ; mutmut 3
n'expose pas le statut par mutant en CLI, donc les **taux** par module n'ont pas
été recalculés — seuls les totaux et la liste des survivants le sont.

| module | mutants | tués | survivants | taux |
|---|---|---|---|---|
| `router.py` | 893 | 682 | 211 | 76 % |
| `rerank.py` | 554 | 393 | 161 | 71 % |
| `indexer.py` | 421 | 354 | 67 | 84 % |
| `util.py` | 337 | 152 | 185 | 45 % |
| `evaluate.py` | 300 | 212 | 88 | 71 % |

`util.py` reste le point faible (45 %) : c'est le bord I/O. Ses chemins d'échec
sont maintenant couverts (`TestDurability`), mais ses corps de boucle ne le sont
pas.

## Par fonction (≥ 8 mutants couverts, du pire au meilleur)

| fonction | mutants | tués | survivants | taux |
|---|---|---|---|---|
| `_context_tokens` | 10 | 3 | 7 | 30 % |
| `load_cache` | 25 | 13 | 12 | 52 % |
| `shortlist` | 10 | 6 | 4 | 60 % |
| `est_tokens` | 8 | 5 | 3 | 62 % |
| `resolve` | 130 | 82 | 48 | 63 % |
| `truncate` | 15 | 10 | 5 | 67 % |
| `read_text` | 9 | 6 | 3 | 67 % |
| `run` | 203 | 136 | 67 | 67 % |
| `render_bundle` | 140 | 102 | 38 | 73 % |
| `_clean_body` | 15 | 11 | 4 | 73 % |
| `_apply` | 31 | 23 | 8 | 74 % |
| `hr` | 16 | 12 | 4 | 75 % |
| `tokenize` | 28 | 21 | 7 | 75 % |
| `build` | 252 | 196 | 56 | 78 % |
| `detect_packs` | 167 | 130 | 37 | 78 % |
| `coverage` | 41 | 32 | 9 | 78 % |
| `_project` | 71 | 56 | 15 | 79 % |
| `_coverage` | 10 | 8 | 2 | 80 % |
| `_stem_once` | 58 | 47 | 11 | 81 % |
| `suggest_rules` | 69 | 56 | 13 | 81 % |
| `expand_with_origin` | 16 | 13 | 3 | 81 % |
| `save_json` | 32 | 26 | 6 | 81 % |
| `split_sections` | 55 | 45 | 10 | 82 % |
| `_raw_name_parts` | 11 | 9 | 2 | 82 % |
| `gate` | 59 | 49 | 10 | 83 % |
| `_fields` | 56 | 47 | 9 | 84 % |
| `score` | 270 | 229 | 41 | 85 % |
| `report` | 82 | 70 | 12 | 85 % |
| `apply_order` | 74 | 64 | 10 | 86 % |
| `stem` | 8 | 7 | 1 | 88 % |
| `doc_file` | 18 | 16 | 2 | 89 % |
| `card` | 12 | 11 | 1 | 92 % |
| `score_sections` | 78 | 76 | 2 | 97 % |
| `_doc` | 47 | 46 | 1 | 98 % |
| `_overlap` | 9 | 9 | 0 | 100 % |
| `load` | 15 | 15 | 0 | 100 % |
| `_key` | 15 | 15 | 0 | 100 % |
| `load_json_soft` | 9 | 9 | 0 | 100 % |
| `stats` | 43 | 43 | 0 | 100 % |
| `_ids` | 8 | 8 | 0 | 100 % |
| `reranked_results` | 8 | 8 | 0 | 100 % |

## La passe n'était pas finie : trois défauts trouvés APRÈS le score

Le mutation testing ne trouve pas cette classe de bug. Il faut se demander « et
si c'est interrompu ? » au lieu de « est-ce que ça marche ? ».

**1. Perte de données sur écriture interrompue.** `save_cache` écrivait le
fichier cible en place. Disque plein → fichier tronqué → `load_cache` renvoyait
un dict vide **sans un mot** → la sauvegarde suivante écrasait la preuve.
**136 jugements perdus, rien dans les logs.** Reproduit avant correction, corrigé
par écriture atomique (temporaire + `fsync` + `rename`), et `load_cache` met
désormais la copie corrompue de côté (`.corrupt`) en criant sur stderr.

**2. Écritures concurrentes perdues.** `apply_order` fait lire-modifier-écrire
sans verrou. Deux process : **10 jugements écrits, 5 sur disque.** Corrigé par
`flock` sur un fichier voisin (le fichier de données est remplacé par rename,
donc le verrouiller lui-même n'exclurait rien). Même correctif appliqué à
`feedback`, `session` et l'état des hooks.

**3. Score non déterministe.** En passant les champs en `set` pour la vitesse,
un `" ".join(ensemble)` a rendu le bonus de bigramme dépendant de
`PYTHONHASHSEED` : **la même requête valait 21,98 ou 18,80 selon le process**.
Attrapé par un test qui lance deux sous-processus avec des seeds différents —
invisible autrement, puisque le seed est constant dans un process.

Les trois ont un test qui **échoue sur le code d'avant** (vérifié en le
restaurant).

## Un gain de performance gratuit

`router.score` : **10 ms → 5 ms** (2×), sans changement de comportement. Les
champs tokenisés sont passés de listes à des ensembles (`t in liste` était
linéaire sur ~150 tokens × 607 documents) et `df` ne parcourt plus que les
champs qui comptent. Budget déclaré inchangé (50 ms), marge 9,4×.

## Une idée mesurée et rejetée

Le routeur ne lisait pas les mots-clés des 4 906 sections déjà indexées. Sur des
requêtes jamais vues, la bonne réponse était classée 6e ou pire pendant qu'un
`command:flutter-build` gagnait sur le mot « flutter ». Ajouter ce champ comme
signal de scoring :

- sur les 94 requêtes tenues à l'écart : **+0,0 point net** (6 requêtes gagnées,
  6 perdues), bootstrap apparié, IC95 [−5,3 ; +5,3] ;
- sur le jeu de réglage, plat de 0,15 à 0,5 puis en baisse à 0,7.

**Rejeté et retiré du code**, avec le chiffre et l'intervalle consignés dans
`router.FIELD_WEIGHT`. Une idée plausible qui ne survit pas à la mesure est une
idée rejetée, pas une idée en attente. C'est le deuxième résultat négatif du
projet, après Rocchio.



## Trier par conséquence, pas par nombre (la règle que j'applique)

Les 467 survivants restants ne valent pas tous un test. La question n'est pas
« combien de mutants », c'est « quelle conséquence observable si le code est
faux ? ». Trois familles, trois réponses :

| famille | test | exemple mesuré |
|---|---|---|
| **conséquence utilisateur** | **corriger le code**, puis un test | `--budget 400` rendait 1 983 tokens : la promesse de l'outil était fausse |
| **conséquence interne** (mauvaise réponse silencieuse) | un test | `_key` : changer la normalisation orpheline 136 jugements |
| **aucune conséquence observable** | rien, documenté | `{"javascript", "node"}` : les deux tags alimentent le même jeu de hints |

C'est pour ça que la passe n'est pas « finie à 79,3 % » : le score s'est arrêté,
le **triage par conséquence** non. Il a trouvé un défaut de plus après
l'annonce du chiffre final.

## Trouvé après le score : le budget n'était pas un plafond

`eccx recall --budget` est affiché comme la promesse principale de l'outil
(« 3 500 tokens au lieu de 1 028 343 »). Mesuré :

```
eccx recall --k 8 --budget  400  ->  1 983 tokens   (5,0x)
eccx recall --k 8 --budget 1000  ->  1 684 tokens   (1,7x)
```

Cause : `render_bundle` allouait une part par document puis imposait un
**plancher de 250 tokens** par document, sans jamais re-vérifier le total. Avec
8 documents, le plancher seul valait 2 000 tokens.

Aucun test ne l'avait vu parce que **tous mesuraient la qualité** (quel
composant sort en premier), aucun ne mesurait **la quantité** — le seul chiffre
que l'outil imprime sur sa propre bannière.

Corrigé : le budget couvre maintenant la sortie entière, bannière et plan de
route compris ; les documents sont ajoutés tant qu'ils tiennent ; le coût de
chaque bloc est mesuré après assemblage (en-tête inclus). Vérifié sur une
grille **k × budget × requête** (80 points, 0 dépassement) et par un test de
propriété dans la suite unitaire.

Un test antérieur, `test_every_document_keeps_a_minimum_floor`, **encodait le
défaut** : il exigeait que les 6 documents soient présents avec 400 tokens de
budget. Remplacé par le contrat réel (« plus de budget = plus de documents »),
avec la raison écrite dans le docstring.

## Ce que le tri a effectivement corrigé (passe du 2026-10-28)

Les trois défauts qui restaient en tête de liste ont été corrigés, chacun avec
un test qui **échoue sur l'ancien code** — vérifié en réintroduisant le bug.

### 1. `resolve` arrêtait la cascade sur une projection

La règle de confiance est écrite dans le docstring de `resolve` : *un jugement
n'est concluant qu'à la profondeur pour laquelle il a été fait*. Le code la
contredisait, parce qu'il dérivait « exact » de `coverage >= 1.0`.

Repro : jugement appliqué sur un pool de 20, résolution à `k=15`. Le pool
courant est un sous-ensemble du pool jugé, donc `coverage = 1.0` — et le
`overlap` vaut 1,0 lui aussi. `_project` renvoyait le jugement, `resolve`
s'arrêtait au **premier** palier avec `projected: False`, `steps: [15]`.
Un jugement fait à 20 rejoué à 15 est une projection : la réponse était fausse
**sans erreur**.

`coverage` et « exactitude » répondent à deux questions différentes :

- *coverage* : le juge a-t-il vu tout ce que je m'apprête à classer ?
- *exactitude* : est-ce le même pool ?

Un jugement sur un sur-ensemble satisfait la première et pas la seconde.
`_project` renvoie maintenant `(ordered, record, exact)` — `exact` est un fait,
plus une inférence sur un ratio.

### 2. `--expand` était ignoré dès que `--rerank` était actif

`evaluate.run` calculait les poids Rocchio puis appelait `rr.resolve(...)` sans
les passer : `resolve` n'acceptait même pas `term_weights`. Mesuré : la
combinaison `--expand --rerank` était **identique au octet** à `--rerank` seul
(72,0 % @1 dans les deux cas). Un flag qui ne fait rien et ne le dit pas.

Une fois le poids réellement transmis, la mesure devient possible — et elle
n'est pas flatteuse : `--expand` **dégrade** (66,0 % @1 contre 72,0 %), et ne
s'applique qu'à **66 % des requêtes** du jeu de développement. C'est cohérent
avec le résultat négatif déjà documenté sur Rocchio ; la différence est qu'on
peut maintenant le voir dans la sortie au lieu de le supposer.

### 3. Le budget n'était vérifié que par des tests unitaires

Le défaut du budget (1 983 tokens pour `--budget 400`) est passé inaperçu parce
que la suite testait `render_bundle` directement, avec les arguments qui lui
plaisent. La promesse est faite par le **CLI**, bannière et plan de route
compris : c'est le CLI qu'il faut mesurer.

`tools/budget_smoke.py` mesure `stdout` de `./eccx recall` avec le même
compteur que le CLI (`util.est_tokens`) sur 5 requêtes × 2 budgets à `k=8`, et
entre dans le gate. Preuve qu'il attrape le défaut : en rétablissant l'ancien
calcul (`budget_tokens=args.budget`, sans déduire le header), il sort
`716 tokens pour 400 (1,79x)` et **exit 1**.

### Un mot sur `escalated`

`escalated` voulait dire « on a élargi la recherche ». Sur un cache vide, tout
élargit, donc `eccx eval --rerank` affichait **100 % d'escalade à chaque run** —
y compris les runs où aucun jugement n'existait. Le chiffre n'était pas faux, il
était inutile.

Plutôt que de renommer un champ public (quatre tests existants l'utilisent
légitimement), un second champ a été ajouté : `judged_deeper`, vrai seulement
si le jugement retenu a été fait plus profond que `k`. Deux nombres, deux
questions : *a-t-on élargi* / *cela a-t-il servi*.

Le travail sur la qualité du routage sur requêtes inédites — ce qui a été
tenté, mesuré et retiré — est dans `docs/ROUTING-GENERALISATION.md`.

## Prochains tests, dans cet ordre

1. `_context_tokens` : égalité d'ensemble. Conséquence faible, effort faible.
2. `util` : corps de boucle de `stem` / `tokenize` (45 % de mutation, le pire
   module). Conséquence : des requêtes mal tokenisées, donc un routage faux
   silencieux — mais aucun cas connu qui échoue aujourd'hui.
3. `util.save_json` : déjà couvert par `TestDurability` (même chemin de code).
