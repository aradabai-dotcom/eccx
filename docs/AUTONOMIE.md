# eccx sans ECC — ce qui marche, ce qui ne marche pas

Question posée le 2026-10-30 : **eccx est-il un dépôt complet, ou a-t-il besoin
d'ECC pour fonctionner ?** Et : **qu'apporte-t-il qu'ECC n'a pas déjà ?**

Les deux réponses ont une mesure derrière. La seconde est inconfortable.

---

## 1. Trois configurations, trois comportements

Installation du wheel dans un venv, **aucun ECC sur le disque**, `ECC_ROOT`
pointant vers un dossier absent :

| configuration | résultat mesuré |
|---|---|
| installation neuve, aucun index | `exit 2` — `catalogue absent … git clone … \|\| eccx index` |
| index déjà construit, clone supprimé | `exit 0`, routes servies, **corps vides et silencieux** |
| `--corpus DIR` sur un dossier markdown | `exit 0`, routage complet, **aucun ECC** |

La ligne du milieu était le vrai défaut : 1 222 octets renvoyés au lieu de
4 963, les routes intactes, tous les textes évaporés, et **rien sur stderr**.
Cause : `read_text` transforme `OSError` en `""`, donc un fichier absent et un
fichier vide sont le même objet. Corrigé — `recall` annonce désormais
`content unavailable for N/M route(s)` et nomme le chemin manquant.

Donc la réponse honnête à « a-t-il besoin d'ECC ? » est **oui pour son mode
principal** (router le catalogue), **non pour le mode `--corpus`** (router vos
documents). eccx n'est pas un produit autonome qui remplacerait ECC : c'est un
outil qui exploite le catalogue ECC, avec une second usage générique.

Deux conséquences à assumer :

- les *mesures* du dépôt (`perf/budgets.py`, `tools/mutate.sh`, la CI) clonent
  ECC épinglé — sans lui, on ne peut pas refaire les chiffres publiés ;
- le corpus `restaurant-suite` est épinglé dans `skills-local/` : c'est une
  fixture de mesure, pas une dépendance d'exécution.

---

## 2. Le routeur : ECC en a déjà un

`ECC/scripts/lib/context-retrieval.js` (206 l.) fait du BM25F avec n-grammes
hachés et fusion RRF sur 292 entrées, sans réseau ni poids.
`ECC/scripts/lib/context-selection.js` (441 l.) y ajoute l'auto-admission
(`AUTO_ADMIT_MIN_BM25=20`, `FALLBACK_MIN_BM25=12`, `MAX_SELECTED=8`). Les deux
sont appelés au lancement de session, testés et documentés côté ECC.

**« eccx apporte un routeur » est donc faux.** Il fallait mesurer.

### Protocole

Le routeur d'ECC exposé tel quel (`routingEntries()` + `buildRetrievalIndex()` +
`searchRetrieval()`), les mêmes 60 requêtes aveugles que la mesure de routage
(`evals/heldout.jsonl` + `heldout2.jsonl`, écrites avant d'avoir vu le
classement), les mêmes cibles, la même métrique.

**Correction d'équité, faite avant de conclure :** ECC ne route que des
`skill:` (292 entrées). eccx indexe 607 documents — skills, agents, commands,
rules. Sur ces 60 requêtes, **44 contiennent au moins une cible que le routeur
d'ECC ne peut pas atteindre structurellement**. Comparer les deux sans le dire
aurait été une victoire fabriquée. La comparaison retenue restreint donc les
cibles aux skills **des deux côtés** (57 requêtes sur 60).

### Résultat

| armée | @1 | @3 | @5 | @20 |
|---|---|---|---|---|
| ECC (son routeur, skills seuls) | **15/57** (26 %) | **21/57** (37 %) | **25/57** (44 %) | **38/57** (67 %) |
| eccx lexical | **17/57** (30 %) | **24/57** (42 %) | **29/57** (51 %) | **46/57** (81 %) |

Coût mesuré sur cette machine, même requête, 200 itérations après chauffe :
ECC construit son index 292 entrées en 372 ms et route en **1,5 ms/requête** ;
eccx charge 607 documents en 15 ms (index déjà bâti) et route en
**4,1 ms/requête**, soit ~2,7× plus lent par requête et sans commune mesure en
latence perçue. C'est le prix des 607 documents, des sections et du scoring par
champs — pas un argument de vente.

McNemar apparié, 57 requêtes :

| k | eccx gagne | eccx perd | p |
|---|---|---|---|
| @1 | 8 | 6 | 0,79 |
| @3 | 11 | 8 | 0,65 |
| @5 | 9 | 5 | 0,42 |
| @20 | 10 | 2 | **0,039** |

### Ce que ça veut dire

Aux rangs que l'agent utilise vraiment (@1, @3, @5), **l'écart n'est pas
significatif**. eccx n'est pas un meilleur routeur qu'ECC : il en est un
différent, de qualité comparable sur ce jeu. Le seul avantage solide est la
profondeur (@20) — c'est-à-dire le rappel, pas la précision.

Sans la correction d'équité, la même mesure donnait 32 % contre 25 % et un
p de 0,001 à @20. Le chiffre flatteur venait de l'incompatibilité des cibles.
Il est conservé ici pour la raison inverse : c'est exactement le genre d'erreur
que ce dépôt s'interdit.

### 2 bis. Le catalogue plus large ne rapporte rien de mesuré

eccx indexe 607 documents là où le routeur d'ECC en voit 292. J'en avais fait
un argument. Décompte sur les mêmes 60 requêtes aveugles :

| sous-ensemble | n | eccx @1 | ECC @1 | eccx @3 |
|---|---|---|---|---|
| cibles exclusivement skills | 16 | 6 | 4 | 9 |
| cibles mixtes | 41 | 13 | 11 | 20 |
| **aucune cible skill** (commandes, agents) | **3** | **0** | 0 (structurel) | **1** |

Sur les 3 requêtes où seule une commande ou un agent peut répondre — « plan the
work for a two week feature » → `command:plan`, « duplicated logic in three
services » → `agent:refactor-cleaner` — eccx rend **0/3 au rang 1**. ECC ne peut
pas répondre, mais eccx non plus : il sait *citer* un `command:` ou un
`agent:`, pas les *choisir*.

Donc l'argument « il voit plus de composants » est faux en pratique. Trois
requêtes font un échantillon minuscule — la conclusion honnête est « non
démontré », pas « démontré négatif », mais en aucun cas « avantage ».

---

## 3. Alors, quelle valeur ajoutée ?

Pas le retriever. Ce qui reste, et qui tient :

1. **Une mesure publiée avec ses échecs.** 40/60 @1 sur `restaurant-suite`,
   66,7 %, contre `grep` à 8,3 % — et les 20 requêtes ratées sont dans le
   dépôt, pas passées sous silence. ECC mesure `context-selection` par ses
   tests, pas par un jeu de requêtes aveugles rejouable par un tiers.
2. **Le découpage en sections.** 4906 sections sur 607 documents : le routeur
   renvoie le paragraphe, pas le fichier entier — c'est ce qui fait tenir
   `--budget` (9 budgets mesurés, dépassement maximal 1,00×).
3. **Une CI qui refuse.** 560 tests, `hygiene` (ruff, zizmor, pip-audit, build),
   `perf`, `mutation-diff`, sur un ruleset `main` sans acteur dérogatoire.
4. **Un mode `--corpus`** qui route n'importe quel dossier markdown sans ECC.
5. **Un wheel installable** — `pip install`, `--version`, chemins d'état dans
   `~/.eccx`, jamais dans le dossier que vous éditez.

Ce qu'il n'apporte pas : un routeur supérieur, l'autonomie vis-à-vis d'ECC, une
interface graphique, des embeddings par défaut (`--semantic` non recommandé,
faute d'avoir battu le lexical).

---

## 4. Refaire la mesure

```bash
./tools/fetch_ecc.sh                                  # clone épinglé 25278e7
python3 tools/bench_vs_ecc.py --ecc-root ~/ECC        # le tableau du §2
node tools/ecc_router_bench.js evals/heldout.jsonl    # routeur d'ECC seul
python3 -m pytest tests/test_eccx.py -k WithoutECC -q # le tableau du §1
```

`tools/bench_vs_ecc.py` réémet exactement les chiffres ci-dessus, y compris la
restriction aux skills et les p de McNemar. S'il n'y arrive plus, c'est que le
routeur d'ECC a changé : la ligne de base est datée (`25278e7`), pas éternelle.

Les trois tests `TestWhatWorksWithoutECC` figent le tableau du §1 : si le
comportement sans ECC change, la CI rougit au lieu de laisser la doc mentir.
