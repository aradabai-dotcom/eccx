# La CI, et ce qu'elle a coûté à faire tourner

**État : tous les jobs verts.** Run `40977987972` sur `0cce790` — lu dans le
log du runner, pas sur un badge :

| job | résultat | ce que le log dit |
|---|---|---|
| `checks` | **success** | `Ran 523 tests in 241.609s` · `coverage gate: 89% >= 85% PASS` · `ALL CHECKS PASSED` |
| `perf` | **success** | `catalogue absent sous /home/runner/ECC — clonage de …` · `all 9 budgets met` · `1 budget non mesuré : le sémantique, fastembed absent` |
| `mutation` | skipped | manuel, 90 min, à la demande |

La ligne `perf` est la première de son histoire : le job était rouge depuis sa
création et personne ne le lisait, `continue-on-error` aidant. Elle dit aussi
elle-même le budget qu'elle n'a **pas** mesuré, au lieu de le passer par
accident — la faute exacte qui l'avait rendu inutile.

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

## Huitième obstacle : la mutation était une porte que personne ne lisait

`mutation` ne tournait que sur `workflow_dispatch` ou un cron, 90 minutes, et
n'a donc jamais fait partie d'une revue. Ce n'est pas une négligence d'auteur :
c'est la conséquence mécanique d'avoir mis le seul contrôle capable de
détecter un test vide derrière un coût que personne ne paie au quotidien.

**Le raisonnement paresseux** serait de baisser le seuil ou de muter moins de
modules. **Le raisonnement qui tient** est que ces 90 minutes répondent à deux
questions différentes, et qu'on les a confondues :

| question | portée | coût mesuré | quand |
|---|---|---|---|
| la suite est-elle encore sérieuse, partout ? | 5 modules, 2 639 mutants | ~90 min en CI | nuit / à la demande, **avec seuil** |
| ce diff est-il testé ? | les modules **touchés** | **63–99 s** pour 453 mutants | chaque pull request, **informatif** |

Trois détails qui font la différence entre un chiffre et un outil :

1. **La portée est l'intersection avec `only_mutate`**, pas « ce que le diff a
   touché ». `cli.py` change tout le temps et n'est volontairement pas muté :
   l'annoncer en portée promettrait une couverture qui n'existe pas.
   (`tools/mutation_scope.py`, 8 tests.)
2. **mutmut ne prend pas de `--paths`** : sa portée vient de `pyproject.toml`.
   Le run réduit se fait donc dans un `git worktree` jetable avec son propre
   `.mutmut-cache` — sans quoi le cache partagé recompterait les mutants de
   tous les runs complets précédents, et un score de 400 mutants deviendrait
   silencieusement un score de 2 400.
3. **Un worktree est à `HEAD`, pas à l'arbre de travail.** Le premier run a
   mesuré du code périmé : un test renforcé semblait ne rien changer parce
   qu'il n'était pas dans l'arbre mesuré. L'outil copie maintenant les fichiers
   non commités et l'annonce (`arbre de travail : 4 fichier(s) copié(s)`).

**Vérifié en CI, pas seulement en local.** PR #1, run `40992662303` :
`mutation-diff` **success**, 453 mutants, 396 tués / 57 survivants → 87,4 %,
en 215 s (90 s en local : le runner est plus lent, et il clone le catalogue).
Chiffres identiques à la machine — c'est la seule chose qui rend le run local
utile comme pré-vol.

**Et le premier run en CI a échoué** — c'est la seule raison de le faire tourner.
`mutation-diff` tombe sur `CatalogueAbsent` : la suite indexe le vrai
catalogue (`TestRerank`, `TestIndexerBuild`), donc sans `~/ECC` elle casse à la
*collecte*, avant le moindre mutant. Le job `mutation` complet avait exactement
le même défaut, latent parce que jamais exécuté. Corrigé à la source :
`tools/mutate.sh` clone `affaan-m/ECC` s'il manque, l'annonce, et
`ECCX_BENCH_NO_FETCH=1` refuse — la même règle que `perf/budgets.py`, une seule
fois, valable en local comme en CI.

**Le run réduit a trouvé du vrai, tout de suite** — dans du code que je venais
d'écrire. Trois runs successifs, même commande, même portée :

| run | tués | survivants | score | ce qui l'a fait bouger |
|---|---|---|---|---|
| 1 | 382 | 71 | 84,3 % | — |
| 2 | 382 | 71 | 84,3 % | test renforcé, **absent de la sélection `-k` de mutmut** |
| 3 | 391 | 62 | 86,3 % | `TestCatalogueGuard` ajouté à la sélection + arbre de travail copié |
| 4 | 396 | 57 | 87,4 % | deux tests de valeurs par défaut |

Les quatre mutants qui restaient dans `_upstream_skills` et `build` étaient la
même famille : `d.get("extra", {})` et `meta.get("argument-hint", "")`. Les
remplacer par `None` ne change rien pour une fixture qui porte la clé — et
**aucune fixture ne portait la clé absente**. Deux tests de trois lignes ont
tué les quatre. C'est exactement le trou que ce contrôle existe pour trouver,
et il l'a trouvé sur son auteur.

## Neuvième obstacle : la CI testait contre une cible mouvante

`checks` faisait `git clone --depth 1 https://github.com/affaan-m/ECC`. Pas
« clonait une version » : clonait **ce qu'il y avait à la minute où le job
démarrait**. Le 30/10, l'amont est passé de `25278e7` à `b38be6a` entre deux
runs espacés de vingt minutes — 607 → 611 documents, 314 → 317 skills — et
`test_kind_filter_is_a_filter_not_a_rerank` est passé du vert au rouge **sans
qu'une ligne de ce dépôt change**.

Deux défauts distincts, tous deux corrigés :

1. **La fixture bouge.** `ecc-pin.txt` fixe le commit ; `tools/fetch_ecc.sh`
   récupère exactement celui-là (`fetch --depth 1 origin <sha>` + `checkout
   --detach`), refuse d'écraser un dossier qui n'est pas un dépôt, est
   idempotent, et vérifie que le pin est bien un SHA de 40 caractères. Le
   workflow, `perf/budgets.py` et `tools/mutate.sh` passent tous par lui — un
   seul point de vérité, six tests le tiennent.
   **C'est aussi une exigence scientifique** : tous les chiffres publiés ici
   (gates scellées, mesures de corpus) ont été mesurés contre ce commit-là.
   Tester contre une cible mouvante rend ces chiffres irreproductibles, donc
   infalsifiables, donc publicitaires.
2. **Le test dépendait du contenu du catalogue.** Il affirmait
   `len(résultats) == min(20, n_skills)` — une propriété du *catalogue*, pas du
   routeur : elle n'est vraie que si une requête générée aléatoirement touche
   20 skills. La requête fautive, « help with the help hookify hookify », est
   surtout faite de mots vides et ne touche légitimement qu'un skill. La
   propriété testée est maintenant celle qui compte : le filtre `--kind` rend
   **tous les skills qui marquent au moins un point**, jusqu'à 20 — donc pas
   une troncature du top 20 global.

**Bonus trouvé en chemin** : `eccx index` sans `--force` sert le cache tout en
affichant `from $ECC_ROOT`, c'est-à-dire qu'il annonce une reconstruction qui
n'a pas eu lieu. C'est ce qui m'a fait chasser un catalogue de 611 documents
qui était en réalité un index de 607 plus un fichier périmé. Il affiche
désormais la racine **de l'index**, et le signale quand elle diffère de
`ECC_ROOT`.

## Dixième obstacle : c'est moi qui écrivais l'examen

Question posée, et elle est juste : tous les seuils de cette CI sont de moi.
Un repo qui se note lui-même n'est pas noté. La réponse n'est pas de mieux
rédiger mes propres critères, c'est d'ajouter des validateurs **écrits par
d'autres** et de publier ce qu'ils trouvent, y compris contre moi. Job
`hygiene`, à chaque push :

| validateur | ce qu'il a trouvé sur ce dépôt, au premier passage |
|---|---|
| **ruff** `--select F,E9,B` (règles externes) | `die()` appelé 3 fois, importé 0 fois → `NameError` au lieu du message prévu ; `zip()` sans `strict=` à 11 endroits ; clé de dictionnaire dupliquée ; **2 classes de tests définies deux fois — 7 tests jamais exécutés** |
| **zizmor** (audit externe des workflows) | 24 constats : 9 actions non épinglées, 5 permissions trop larges, 4 credentials persistés dans les artefacts, et **1 injection de code** — `github.base_ref` interpolé dans un `run:` du job que je venais d'écrire |
| **pip-audit** (base CVE externe) | **aucune vulnérabilité** dans ce que l'utilisateur installe (wheel + `numpy`, et avec `fastembed`). Le premier passage signalait `tornado`/`urllib3` : c'était l'outillage du bac à sable, pas le produit — la distinction est vérifiable, pas rhétorique |
| **packaging** (build + install dans un venv neuf) | le wheel s'installe et route ; mais `eccx --version` n'existait pas, et `eccx --corpus X corpus build` **ignorait X** et indexait le dossier courant |

Les trois derniers défauts de `ruff` et `zizmor` sont dans du code **que
j'avais écrit dans cette session**. C'est l'argument le plus honnête en faveur
de l'externalisation : un auteur ne voit pas ce qu'il vient d'écrire.

Deux garde-fous ont été ajoutés pour que ces trous ne reviennent pas :
`test_no_test_class_is_defined_twice` (Python jette silencieusement la
première définition) et trois tests de CLI qui exercent `--version`, le chemin
`die()` et `--corpus … corpus build` — tous découverts par installation propre,
aucun par lecture.

**Ce que ces validateurs ne peuvent pas dire** : si les 60 requêtes de mesure
sont les bonnes, si 78,3 % @3 suffit pour *votre* usage, ou si l'architecture
est la bonne. Ces jugements-là restent les miens, et c'est pourquoi les
chiffres sont publiés avec leurs échecs et leur protocole, pas avec un badge.

## Onzième obstacle : la CI n'était pas une porte

Tout ce qui précède rendait la CI **honnête**. Rien de tout cela ne la rendait
**obligatoire**. Sur un dépôt privé avec un compte GitHub gratuit, GitHub
refuse à la fois la protection de branche et les rulesets (`403`). `main`
pouvait donc recevoir un commit rouge, et rien ne l'en empêchait.

**Fermé le 30/10**, dépôt passé en public (choix explicite du propriétaire),
puis règle de dépôt `main: revue obligatoire et checks verts` :

- suppression de `main` interdite, historique non réécrivable (`non_fast_forward`) ;
- `checks` et `hygiene` déclarés **obligatoires**, avec
  `strict_required_status_checks_policy` (la branche doit être à jour avant
  fusion) ;
- **aucun acteur exempté** (`bypass_actors: []`), administrateur compris.

**Prouvé, pas supposé.** Sonde : un commit trivial poussé directement sur
`main` —

```
remote: error: GH013: Repository rule violations found for refs/heads/main.
remote: - 2 of 2 required status checks are expected.
 ! [remote rejected] HEAD -> main (push declined due to repository rule violations)
```

Première tentative de preuve **ratée** et corrigée : le rejet observé était un
`non-fast-forward` (dépôt local en retard), ce qui ne prouve rien sur la
règle. Refait après synchronisation, pour obtenir `GH013`.

Conséquence pratique : chaque changement passe désormais par une branche et une
pull request. Ce n'est pas une gêne, c'est le contrôle qui manquait — et c'est
la seule façon d'avoir une revue avant `main` quand on travaille seul.

## Ce que la CI vérifie réellement## Ce que la CI vérifie réellement

`run-checks.sh` sur un runner Ubuntu 3.12, après avoir cloné `affaan-m/ECC`
dans `$HOME/ECC` et calculé les 4 906 vecteurs de sections :

- 551 tests, couverture 89 % (seuil 85 %), en sous-processus compris
- 8 barres de routage scellées, dont `heldout5` @20 ≥ 70 % et `heldout9` @20 ≥ 80 %
- le budget de tokens comme promesse dure (CLI, `--budget 400/1000`)
- le chemin `--corpus` de bout en bout (build, recall, eval) sur un dossier jetable
- `ECC @ <commit>` non modifié

## Ce qu'elle ne fait pas

- **Pas de latence bloquante.** `perf/` tourne sur `main` en `continue-on-error` :
  un runner partagé est bruité, un échec temporel n'est pas une régression — un
  échec de *mesure* (catalogue absent, commande en erreur), si.
- **Pas de mutation complète à chaque push.** 90 minutes : planifiée. Un run
  réduit au diff tourne sur chaque PR (`mutation-diff`), informatif — voir
  l'obstacle 8 pour la mesure et la raison de ne pas le rendre bloquant.
- **Pas de cache.** `.eccx/vectors.npy` est recalculé à chaque run (~9 min).
  `actions/cache` est le premier gain évident : 15 min → 3 min.
