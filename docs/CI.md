# La CI, et ce qu'elle a coûté à faire tourner

**État : `checks` vert, `perf` en cours de réparation sans toucher au YAML.**
Dernier run vérifié, `40973525221` sur `2e54290` : `checks` **success**,
518 tests, couverture 89 %, `ALL CHECKS PASSED` — lu depuis le log du runner,
pas depuis un badge. Le commit courant en compte 523 ; son run est celui qui
fait foi quand il arrive. `perf` était rouge pour une raison désormais nommée par lui-même
(« aucun skill amont sous `/home/runner/ECC` ») ; le correctif ne passe pas par
le workflow, que GitHub refuse de modifier sans le scope `workflow` (voir
l'obstacle 7). Il passe par le banc lui-même.

## Ce que le chemin a révélé

Sept obstacles, tous réels, aucun imaginaire. Ils sont notés ici parce que
chacun se reproduira pour la personne qui forke ce dépôt.

| # | obstacle | symptôme | cause |
|---|---|---|---|
| 1 | `eccx index` n'existait pas | `invalid choice: 'index'` | commande documentée partout (README, PUSH.md, CI), implémentée nulle part |
| 2 | scripts en `100644` | `./eccx: Permission denied` (exit 126) | `core.fileMode=false` dans la sandbox masquait le bit ; un clone sur runner le respecte |
| 3 | `timeout-minutes: 20` | job tué avant la fin | valeur écrite avant que les sections existent (9 min d'embeddings en plus) |
| 4 | `[dev]` sans `fastembed` | barres de routage impossibles à passer | les barres sont mesurées avec la couche sémantique |
| 5 | `.github/workflows/*` refusé au push | `refusing to allow an OAuth App to...` | jeton sans la permission `Workflows` |
| 6 | `Contents` manquant | `Write access not granted` | fine-grained PAT : `Contents` et `Workflows` sont deux permissions distinctes |

Les obstacles 5 et 6 ont coûté quatre autorisations successives. La cause
racine des trois premières tentatives : les identifiants embarqués dans `gh`
appartiennent à une **GitHub App**, qui ignore les scopes OAuth et exige une
installation sur le dépôt. Un PAT fine-grained a réglé la question en une fois.

## Septième obstacle : le job `perf` était rouge depuis sa naissance

Il a fallu le lire pour le croire. `perf` lançait `python3 perf/budgets.py` sans
`pip install` ni clone du catalogue : `indexer.load()` retombait sur les trois
skills locaux, `eval` mesurait un catalogue vide et sortait en 1, et le
harnais — `subprocess.run(..., check=True)` avec sortie capturée — jetait la
seule phrase qui expliquait pourquoi. Le job n'a jamais mesuré une seule
latence.

**Le premier correctif a été refusé par GitHub, et c'est instructif.** Réparer
le YAML — installer `[dev]`, cloner `affaan-m/ECC` — a été écrit, testé, vert
en local, et impossible à pousser :

```
! [remote rejected] refusing to allow an OAuth App to create or update
  workflow `.github/workflows/checks.yml` without `workflow` scope
```

Un jeton OAuth avec `repo` **ne peut pas** modifier `.github/workflows/`, même
quand il a `admin` sur le dépôt : le scope `workflow` est un scope classique,
distinct, et un PAT fine-grained ne le remplace pas non plus (`Workflows` y est
une permission à part). Constat vérifié : le jeton disponible ici porte
`gist, read:org, repo` — et pas `workflow`.

Plutôt que d'exiger un jeton plus large, **le besoin a été supprimé**. Un banc
qui dépend d'une fixture doit savoir la chercher :

- `ensure_catalogue()` clone `affaan-m/ECC` si `$ECC_ROOT/skills` est absent,
  en l'annonçant, une seule fois. `ECCX_BENCH_NO_FETCH=1` rétablit l'échec dur
  pour qui veut un run hermétique.
- Le harnais dit ce que l'enfant a dit (`cli()`).
- Les benchmarks ne mesurent plus que ce qu'ils prétendent mesurer : `recall`
  et `eval` passent `--no-semantic`. Sans ce drapeau, le même budget valait
  0,17 s ici et 1,27 s là, selon ce qui traînait sur l'hôte.
- **Le budget sémantique disparaît quand le modèle est absent.** Sans
  `fastembed`, `recall --semantic` retombe sur le lexical *sans le dire* :
  mesuré à 0,153 s dans un venv nu contre 1,271 s avec le modèle. Un budget
  qui passe à 25× sous sa limite en ne mesurant rien n'est pas un budget, donc
  il n'est pas compté — et le run l'écrit.

La correction du harnais a immédiatement révélé le pire : en testant le
garde-fou, `indexer.build()` **a écrasé un index de 607 documents par un index
de 3**. `load()` a ensuite servi cet index cassé indéfiniment — non vide, bonne
version — et le seul symptôme était un rappel de 0 %. Corrigé côté produit :
`build()` refuse d'écrire un index sans skill amont (`CatalogueAbsent`, code de
sortie 2, index existant intact) et `load()` ne sert plus jamais un cache qui
ne contient pas de catalogue.

## Ce que la CI vérifie réellement

`run-checks.sh` sur un runner Ubuntu 3.12, après avoir cloné `affaan-m/ECC`
dans `$HOME/ECC` et calculé les 4 906 vecteurs de sections :

- 523 tests, couverture 88 % (seuil 85 %), en sous-processus compris
- 8 barres de routage scellées, dont `heldout5` @20 ≥ 70 % et `heldout9` @20 ≥ 80 %
- le budget de tokens comme promesse dure (CLI, `--budget 400/1000`)
- le chemin `--corpus` de bout en bout (build, recall, eval) sur un dossier jetable
- `ECC @ <commit>` non modifié

## Ce qu'elle ne fait pas

- **Pas de latence bloquante.** `perf/` tourne sur `main` en `continue-on-error` :
  un runner partagé est bruité, un échec temporel n'est pas une régression — un
  échec de *mesure* (catalogue absent, commande en erreur), si.
- **Pas de mutation à chaque push.** 90 minutes ; manuel ou planifié.
- **Pas de cache.** `.eccx/vectors.npy` est recalculé à chaque run (~9 min).
  `actions/cache` est le premier gain évident : 15 min → 3 min.
