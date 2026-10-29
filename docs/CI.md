# La CI, et ce qu'elle a coûté à faire tourner

**État : vert.** Run n°2, commit `cbc0127`, 503 tests, couverture 89 %,
`ALL CHECKS PASSED` — lu depuis le log du runner, pas depuis un badge.

## Ce que le chemin a révélé

Six obstacles, tous réels, aucun imaginaire. Ils sont notés ici parce que
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

## Ce que la CI vérifie réellement

`run-checks.sh` sur un runner Ubuntu 3.12, après avoir cloné `affaan-m/ECC`
dans `$HOME/ECC` et calculé les 4 906 vecteurs de sections :

- 503 tests, couverture 89 % (seuil 85 %), en sous-processus compris
- 8 barres de routage scellées, dont `heldout5` @20 ≥ 70 % et `heldout9` @20 ≥ 80 %
- le budget de tokens comme promesse dure (CLI, `--budget 400/1000`)
- le chemin `--corpus` de bout en bout (build, recall, eval) sur un dossier jetable
- `ECC @ <commit>` non modifié

## Ce qu'elle ne fait pas

- **Pas de latence bloquante.** `perf/` tourne sur `main` en `continue-on-error` :
  un runner partagé est bruité, un échec temporel n'est pas une régression.
- **Pas de mutation à chaque push.** 90 minutes ; manuel ou planifié.
- **Pas de cache.** `.eccx/vectors.npy` est recalculé à chaque run (~9 min).
  `actions/cache` est le premier gain évident : 15 min → 3 min.
