# La CI, et ce qu'elle a coûté à faire tourner

**État : vert sur le code, un job non bloquant encore rouge.** Dernier run,
commit `2e54290` (run `40973525221`) : `checks` **success**, 518 tests,
couverture 89 %, `ALL CHECKS PASSED` — lu depuis le log du runner, pas depuis
un badge. `perf` échoue pour une raison connue et nommée par lui-même
(« aucun skill amont sous `/home/runner/ECC` ») : le correctif est écrit et
committé localement, et attend un jeton portant le scope `workflow` — que
GitHub exige pour toute modification de `.github/workflows/`, quel que soit le
droit d'écriture par ailleurs.

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
latence. Trois corrections, dans cet ordre :

1. **Le harnais dit ce que l'enfant a dit** (`perf/budgets.py: cli`).
2. **Le job installe ses dépendances et clone `affaan-m/ECC`**, comme le job
   `checks`. `eccx vectors` reste dehors : 9 min sur un job limité à 10.
3. **Les benchmarks sont indépendants de la machine.** `recall` et `eval`
   activent le sémantique dès que des vecteurs traînent sur l'hôte : le même
   budget mesurait 0,17 s ici et 1,27 s là. Ils sont désormais passés avec
   `--no-semantic`, et le coût du modèle est un budget **séparé et déclaré**
   (3,81 s), mis côte à côte avec le bénéfice mesuré — qui est nul.

La correction (1) a immédiatement révélé le pire : en testant le garde-fou,
`indexer.build()` **a écrasé un index de 607 documents par un index de 3**.
`load()` a ensuite servi cet index cassé indéfiniment — non vide, bonne
version — et le seul symptôme était un rappel de 0 %. C'est corrigé côté
produit, pas côté CI : `build()` refuse d'écrire un index sans skill amont
(`CatalogueAbsent`, code de sortie 2, index existant intact) et `load()` ne
sert plus jamais un cache qui ne contient pas de catalogue.

## Ce que la CI vérifie réellement

`run-checks.sh` sur un runner Ubuntu 3.12, après avoir cloné `affaan-m/ECC`
dans `$HOME/ECC` et calculé les 4 906 vecteurs de sections :

- 518 tests, couverture 89 % (seuil 85 %), en sous-processus compris
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
