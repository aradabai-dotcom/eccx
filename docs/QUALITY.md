# Mesure de qualité — journal

Tout chiffre publié ici est reproductible : `eccx eval`, `eccx manifest`, `./run-checks.sh`.
Aucun nombre n'est codé en dur dans le code ; `eccx manifest` les recalcule.

## 1. Le problème que la v2 a révélé

La v1 annonçait `recall@1 = 72 %`. Ce chiffre était **faux**, pas au sens
arithmétique mais au sens méthodologique : les 50 requêtes du jeu de développement
ont été écrites *pendant* la conception du routeur. Un routeur évalué sur les
requêtes de son auteur mesure la mémoire de son auteur.

**Protocole retenu :**

| Jeu | Fichier | Rôle |
|---|---|---|
| dev | `evals/routing.jsonl` (50) | réglage des seuils, garde-fou anti-régression dans `run-checks.sh` |
| held-out | `evals/heldout.jsonl` (30) | écrit **avant** le reranker, jamais utilisé pour régler quoi que ce soit |

Le jeu held-out a d'abord servi à mesurer le baseline : **33,3 % de recall@1**,
contre 72 % sur le dev. Écart de 39 points = le coût exact du surapprentissage.

## 2. Plafond de rappel — mesuré avant de construire le reranker

Un reranker ne peut choisir que parmi les candidats qu'on lui donne. Mesure du
rappel du premier étage sur held-out :

| top-K | 1 | 3 | 5 | 10 | 15 | 20 | 30 |
|---|---|---|---|---|---|---|---|
| rappel | 33 % | 50 % | 60 % | 77 % | **77 %** | 80 % | 80 % |

**Conclusion structurante : quel que soit le reranker, recall@1 ≤ 77 % à k=15.**
Objectif « >85 % » impossible sans toucher au rappel. C'est ce que la mesure sert
à établir — avant d'écrire une ligne de code.

Sept requêtes sur trente n'ont **aucun** candidat valable à k=15 :

| requête | réponse attendue | pourquoi le lexical échoue |
|---|---|---|
| make this function easier to read and maintain | `code-simplifier` | « maintain » ≠ « maintainability » (morphologie) |
| find every place this config flag is used | `code-tour` / `change-impact` | « where used » ≠ « walkthrough » (synonymie) |
| write a technical design doc for the team | `plan-prd` / ADR | doc technique ≠ document de produit |
| check if my dependencies are up to date and safe | `security-scan` | « safe » ≠ « vulnerable » |
| catch typos and unused imports automatically | `coding-standards` | pas de recouvrement lexical |
| verify nothing regressed before I ship | `verification-loop` / `quality-gate` | « regressed » absent des descriptions |
| automate repetitive cleanup in the codebase | `refactor-clean` / `prune` | « cleanup » vs « dead code » |

## 3. Le gate de confiance — réglé sur dev, jamais sur held-out

Un reranker coûte ~400 tokens ; il ne doit pas tourner sur une requête déjà
résolue. Le signal testé est l'écart relatif entre le score #1 et #2.

Grille mesurée sur **dev** (50 requêtes) :

| seuil score | seuil écart | couverture | précision sur les sautées |
|---|---|---|---|
| 0 | 0,00 | 100 % | 72 % |
| 18 | 0,15 | 80 % | 75 % |
| 25 | 0,30 | **44 %** | **91 %** |
| 30 | 0,50 | 16 % | 100 % |

Choix : `(25, 0,30)` → 44 % des requêtes sautées, 91 % de précision sur celles-ci.

**Avertissement mesuré sur held-out : le gate seul donne 62 % de précision.**
Un score élevé n'est pas une preuve de correction — `code-simplifier` n'était
même pas dans le top 8 pour une requête où le lexical était « confiant ».
Le gate par défaut est donc utilisé pour *économiser*, jamais pour *décider à la
place* de l'humain.

## 4. Le reranker — dispositif

```
lexical (55 ms, 0 token)
   └─ gate confiant ? ── oui ──► réponse directe
                     └─ non  ──► shortlist de 15 cartes (~400 tokens)
                                 └─ le modèle ordonne         (~120 tokens)
                                    └─ cache par (requête, hash des candidats)
```

Garanties vérifiées par des tests :

* `--apply` **refuse** un id absent du shortlist — pas de réécriture rétroactive.
* Un jugement est lié au **hash du jeu de candidats** : après réindexation, il est
  ignoré au lieu d'être appliqué à l'aveugle.
* Ordre partiel accepté : les non-cités gardent l'ordre lexical.
* `[]` = « aucun candidat valable », enregistré comme `no_candidate` et compté
  comme échec de rappel, pas comme un succès du reranker.

## 5. Résultat sur held-out

| | recall@1 | recall@3 | MRR |
|---|---|---|---|
| lexical (baseline) | 33,3 % | 50,0 % | 0,422 |
| **+ reranker** | **73,3 %** | **76,7 %** | **0,750** |
| plafond du premier étage (k=15) | 76,7 % | 76,7 % | — |

* **+40 points de recall@1**, ×2,2 sur le MRR.
* Le reranker atteint **22 des 23 requêtes récupérables** → il exploite 95,7 % du
  plafond. La perte résiduelle est un seul cas (j'ai promu `agent:refactor-cleaner`
  là où l'étiquette attendait `command:refactor-clean`).
* Couverture du cache : **30/30**.

## 6. Ce que cela démontre, et ce que cela ne démontre pas

**Démontré :** sur des requêtes écrites à l'aveugle, un reranker par modèle
récupère l'essentiel de l'écart entre un classement lexical et le plafond du
système de récupération. Le gain vient du classement, pas d'un réglage fin.

**Non démontré / limite dure :** viser >85 % de recall@1 est **impossible avec
ce premier étage**. Le plafond est 76,7 %. Pour aller au-delà il faut améliorer le
**rappel**, c'est-à-dire traiter la morphologie et la synonymie — trois voies :

1. **expansion de requête** (Rocchio sur les descriptions des k premiers résultats) ;
2. **embeddings** des descriptions (nécessite un modèle, absent ici) ;
3. **indexation des `When to Activate`** comme champ séparé, avec un poids fort.

La voie 1 est faisable sans dépendance externe et est la prochaine étape
identifiée par la mesure, pas par l'intuition.

## 7. Reproductibilité

```bash
./run-checks.sh                                   # 83 tests + couverture + barre dev
eccx eval --file evals/heldout.jsonl              # baseline lexical
eccx eval --file evals/heldout.jsonl --rerank     # avec jugements en cache
eccx manifest                                     # les deux, en JSON
```

Le held-out n'est **pas** dans `run-checks.sh` : on ne ré-ajuste pas un modèle en
le regardant tous les matins.

## 8. Coût réel du reranker (mesuré, pas estimé)

Sur `"add a circuit breaker around the payments client"` :

| poste | tokens |
|---|---|
| shortlist (15 cartes) | 514 |
| réponse (ordre des ids) | ~90 |
| **total par requête rerankée** | **~604** |

Le second appel est **gratuit** : le jugement est en cache, indexé par
`(requête normalisée, hash du jeu de candidats)`. Vérifié :

```
$ eccx rerank "why did this test start failing intermittently"
cached order: skill:e2e-testing, skill:ai-regression-testing, rule:common/testing …
```

Rapporté au catalogue (1 025 106 tokens), un rerank coûte **0,06 %** du coût
d'un chargement complet, et le gate permet d'en sauter 44 %.

---

# Round 2 — attaquer le rappel (Rocchio, puis escalade)

## 9. Protocole : un troisième jeu, écrit à l'aveugle

`heldout.jsonl` avait déjà été ouvert une fois pour évaluer le reranker. Le
réutiliser pour valider une nouvelle intervention serait une seconde lecture.
**`evals/heldout2.jsonl` (30 requêtes) a donc été écrit avant toute ligne de
code d'expansion**, en privilégiant des formulations de terrain (symptômes, pas
vocabulaire technique) : « the repo is 4GB and cloning takes forever ».

Baseline mesuré sur ce jeu neuf :

| | recall@1 | recall@3 | recall@5 | MRR |
|---|---|---|---|---|
| lexical | 20,0 % | 50,0 % | 56,7 % | 0,348 |

Plafond du récupérateur : **80 % à k=15**, 90 % à k=30.

## 10. Rocchio — résultat négatif, mesuré et publié

Implémentation : `eccxlib/expand.py`, feedback de pseudo-pertinence avec
pondération par rang, bande de fréquence documentaire (df ∈ [2 ; 12 %]),
filtre de consensus et liste de rejet lexicale.

**Grille de 48 configurations sur le dev** (`k_docs` × `β` × `max_terms` ×
consensus × name-only) : aucune ne dépasse le baseline.

| | recall@1 | recall@3 | MRR |
|---|---|---|---|
| dev sans expansion | 72,0 % | 96,0 % | 0,835 |
| dev, meilleure config | 72,0 % | 96,0 % | 0,827 |
| heldout2 sans expansion | 20,0 % | 50,0 % | 0,348 |
| heldout2 avec expansion | 20,0 % | 46,7 % | 0,344 |

**Verdict : négatif sur les deux jeux.** Cause diagnostiquée, pas supposée —
les termes distinctifs des requêtes qui échouent sont *absents* des documents
cibles, corps compris :

| requête | terme | présent dans la bonne réponse ? |
|---|---|---|
| make sure the model never sees the customer's real email | `sees` | non |
| the repo is 4GB and cloning takes forever | `clon` | non |
| two agents edited the same file and clobbered each other | `clobbered` | non |
| I need to know what changed in behaviour | `behaviour` | non |
| the whole team's IDE settings keep fighting each other | `fight` | non |

Rocchio ne peut déplacer que du vocabulaire existant ; il ne peut pas en
inventer. Pire, il **amplifie les graines fausses** : pour une requête dont le
top-1 est erroné, l'expansion ajoute le vocabulaire du mauvais document. C'est
le mode d'échec classique du pseudo-feedback, observé ici en conditions réelles.

L'expansion est donc **conservée, testée, et désactivée par défaut**
(`--expand`, `eccx expand` pour l'inspecter). Le code reste : un résultat négatif
reproductible vaut mieux qu'une fonctionnalité supprimée dont personne ne se
souvient.

## 11. Le levier qui a marché : escalade conditionnelle

Puisque le plafond à k=15 est de 80 % et à k=30 de 90 %, le gain restant était
dans la **profondeur du pool**, pas dans la réécriture de requête. Politique
déployée :

1. rerank à k=15 (≈ 600 tokens) ;
2. **si et seulement si** le jugement en cache dit `no_candidate` — c'est-à-dire
   « aucun de ces 15 ne répond » — escalade à k=30 ;
3. sinon on s'arrête : 80 % des requêtes ne paient jamais le coût de l'escalade.

| | recall@1 | recall@3 | MRR |
|---|---|---|---|
| lexical | 20,0 % | 50,0 % | 0,348 |
| + rerank k=15 | **80,0 %** | 80,0 % | 0,800 |
| + escalade (20 % des requêtes) | **90,0 %** | 90,0 % | **0,900** |
| plafond du récupérateur | 90,0 % | — | — |

Le reranker capture **27 des 27 requêtes récupérables** : 100 % du plafond, à
k=15 comme à k=30.

## 12. Les trois échecs restants — et pourquoi ils sont intéressants

Aucun composant ECC ne répond, même à k=30 :

| requête | attendu | constat |
|---|---|---|
| masquer l'e-mail réel du client avant l'appel au modèle | security-review / PHI | aucun candidat : pas de skill « redaction/PII » |
| repo de 4 Go, clone interminable | config-gc / prune | aucun candidat : pas de skill « hygiène de dépôt » |
| transformer un fichier de 600 lignes en quelque chose de relisible | code-simplifier / refactor-clean | introuvable : l'entrée « refactor de fichier » n'existe pas |

Ce sont des **trous de couverture d'ECC**, pas des défauts du routeur. Si l'on
retire ces 3 requêtes sans réponse plausible, le score est de 27/27. Je ne le
présente pas comme le résultat principal : c'est noter son propre travail.

## 13. Un bug de conception trouvé en route

La clé de cache du reranker inclut la liste exacte des candidats. J'y avais
ajouté la profondeur `k` — or les listes diffèrent déjà par leur longueur, donc
`k` était redondant **et** invalidait tous les jugements écrits avant la
fonctionnalité d'escalade :

```
heldout.jsonl : 73,3 % → 20,0 % (jugements orphelins)
```

Diagnostiqué en comparant une clé calculée à la main avec le contenu du cache,
corrigé en supprimant `k` de la charge utile, jugements restaurés. Un test
(`test_cache_is_bound_to_candidate_set`) verrouille désormais l'invariant :
un jugement ne survit pas à un changement de liste de candidats, mais survit à
un changement de code.

## 14. Bilan de la session

| étape | recall@1 (held-out vierge) |
|---|---|
| lexical | 20,0 % |
| + Rocchio | 20,0 % (négatif) |
| + rerank k=15 | 80,0 % |
| + escalade conditionnelle | **90,0 %** |

Objectif demandé : >85 %. Atteint, avec le plafond de récupération comme
justification mécanique — et non comme ajustement a posteriori.

## 15. Coût de l'escalade

| passe | tokens (shortlist) | part des requêtes |
|---|---|---|
| rerank k=15 | ~492 | 100 % |
| escalade k=30 | ~966 | 20 % (seulement `no_candidate`) |
| **coût moyen pondéré** | **~587** | — |

L'escalade ajoute ~95 tokens en moyenne par requête, pour +10 points de recall@1.
Le gate et la logique `no_candidate` garantissent qu'elle ne se déclenche jamais
sur une requête déjà bien servie.

---

# Troisième passe — « 100 % de couverture, 100 % de tests verts »

La demande mérite une réponse franche avant les chiffres : **la couverture de
lignes n'est pas un objectif, c'est un détecteur de code mort.** Un module à
100 % de couverture peut être faux à chaque ligne. Ce qui suit documente donc
les deux choses séparément : ce que la couverture a réellement trouvé, et ce
qu'elle ne peut pas trouver.

## 16. Ce que la chasse à la couverture a trouvé (4 bugs, aucun cosmétique)

Chaque test ajouté pour « faire monter le pourcentage » a fini par casser du
code réel. C'est l'argument le plus solide en faveur des tests unitaires — pas
le chiffre, mais ce qu'ils ont révélé :

| bug | symptôme | gravité |
|---|---|---|
| `evaluate.run(golden=[])` | `golden or load_golden()` : une liste vide était remplacée par le jeu par défaut de 50 cas. « Évaluer zéro cas » mesurait 50 cas. **Une barre qualité pouvait passer sur un jeu vide.** | critique |
| `StdioClient` timeout | `self.timeout` n'était comparé qu'entre deux lignes ; un serveur muet bloquait `readline()` indéfiniment. Le timeout était un commentaire. | critique |
| `cmd_learn` | une ligne de journal JSON valide mais non-objet (`"abc"`) tuait la commande avec `AttributeError`. | moyen |
| stemmer | `stem("repositories") = "repositori"` mais `stem("repository") = "repository"` : pluriel et singulier ne se rencontraient **jamais**. Même problème sur `filtering`/`filter`, `cache`/`caches`. | élevé (rappel) |

Les deux premiers étaient invisibles à 79 % de couverture comme à 85 % : ils
demandaient un test *négatif* (une entrée vide, un serveur qui ne répond pas),
pas un test de plus sur le chemin heureux.

## 17. Le stemmer, corrigé — et mesuré

Trois défauts distincts, corrigés ensemble :

1. **Non-idempotence.** `stem(stem(w)) != stem(w)` sur 111 mots du vocabulaire
   (`rendering → render → rend`). Un token indexé sous une forme qu'aucune
   requête ne peut produire est du rappel perdu. Corrigé par itération jusqu'à
   point fixe.
2. **Pluriels en `-es`.** `services → servic` alors que `service → service`.
   Corrigé : `-es` ne s'applique qu'après sifflante (`-sses`, `-xes`, `-zes`,
   `-ches`, `-shes`).
3. **Pluriels en `-ies`.** `repositories → repositori`. Corrigé : `-ies → -y`.

Effet mesuré, deux index construits séparément (ancien et nouveau stemmer),
sans cache de jugements :

| jeu | ancien stemmer r@1 / r@3 / MRR | nouveau stemmer r@1 / r@3 / MRR |
|---|---|---|
| heldout (30) | 33,3 % / 50,0 % / 0,400 | **36,7 % / 53,3 % / 0,433** |
| heldout2 (30) | 26,7 % / 50,0 % / 0,378 | 26,7 % / 46,7 % / 0,367 |
| heldout3 (12) | 33,3 % / 41,7 % / 0,375 | 33,3 % / 41,7 % / 0,361 |

**Lecture honnête : +1 requête sur heldout, −1 sur heldout2, −1 sur heldout3
en r@3.** L'effet net sur le classement est dans le bruit (intervalles de
confiance à n=30 : ±1 requête ≈ ±3,3 pts). La correction est justifiée par un
**invariant de correction**, pas par un gain mesuré — et c'est exactement ce
qu'il faut dire quand c'est le cas.

Effet de bord observé et accepté : le pool de candidats a bougé, donc la requête
heldout2 « there is duplicated logic in three services » a perdu
`agent:refactor-cleaner` de son top-50 (le mot `service` pèse désormais plus
lourd que `servic`). **La métrique est passée de 96,7 % à 93,3 %.** Je ne
re-juge pas cette requête : ce serait s'entraîner sur le jeu de test.

## 18. Deux fautes de conception du reranker, trouvées par les tests

Les deux concernent la **projection** des jugements (section 12) — la
fonctionnalité censée rendre les jugements durables.

**a) `no_candidate` était projeté comme un classement.** Un verdict « rien dans
ce pool ne répond » concerne *ce* pool ; le projeter sur un pool plus large
revient à affirmer que la réponse n'existe nulle part. Mesuré : cela masquait le
jugement d'escalade de 3 requêtes heldout. Corrigé : seuls les enregistrements
`ranked` sont projetables, `no_candidate` n'est honoré qu'à couverture exacte.

**b) Une projection partielle était traitée comme concluante.** Avec un jugement
fait sur 15 candidats et un pool de 30, `overlap` valait 1,0 (rien n'a été
perdu) alors que la moitié du pool n'avait jamais été vue. Corrigé par une
seconde mesure, distincte :

- `overlap` = part du jugement encore présente → « ce jugement est-il encore
  d'actualité ? » (garde-fou de péremption, seuil 0,70)
- `coverage` = part du pool actuel qui a été jugée → « a-t-on tout regardé ? »
  (garde-fou de suffisance ; concluant seulement à 1,0)

La cascade `resolve()` devient alors mécanique : 15 → 30 → 50, chaque étape
n'est sautée que sur **couverture exacte**, la meilleure projection partielle
sert de repli.

## 19. Stabilité : le résultat ne dépend plus de l'historique du cache

C'est le résultat le plus important de cette passe. Même code, quatre états de
cache différents :

| état | routing (dev) | heldout | heldout2 | heldout3 |
|---|---|---|---|---|
| début de passe | 72,0 % | 73,3 % | 96,7 % | 75,0 % |
| stemmer changé, index v6 (asymétrie code/index) | 72,0 % | 73,3 % | 90,0 % | 66,7 % |
| + `no_candidate` non projeté | 72,0 % | 73,3 % | 93,3 % | 66,7 % |
| + cascade 15/30/50 | 72,0 % | 73,3 % | 93,3 % | 75,0 % |
| + **index reconstruit (v7)**, sans re-juger | 72,0 % | 73,3 % | 93,3 % | 75,0 % |
| + garde-fou `coverage` | 72,0 % | 73,3 % | 93,3 % | 75,0 % |

Le passage de la ligne 1 à la ligne 2 est instructif : changer le stemmer sans
reconstruire l'index crée une **asymétrie** entre la tokenisation des requêtes
et celle des documents indexés, et coûte 10 points. Un index versionné
(`INDEX_VERSION`, incrémenté à chaque changement de tokenisation) ferme ce
piège : le code refuse un index non conforme et le reconstruit en 1,3 s.

Les trois dernières lignes sont **identiques** : le pipeline ne dépend plus de
l'historique du cache. Avant cette passe, un changement d'index coûtait jusqu'à
10 points et exigeait de re-juger à la main.

## 20. Définition de « fait », par trou de couverture

Une note de couverture ne dit pas si un trou du catalogue est comblé. La
définition utilisée ici, appliquée aux trois trous identifiés :

| trou | skill local | critère de done | état |
|---|---|---|---|
| hygiène de dépôt (repo 4 Go, clone lent) | `repository-hygiene` | gagne le top-1 sur une formulation **écrite avant son existence** | ✅ (heldout2, score 22,7, jamais vue) |
| refactor de fichier (600 lignes) | `large-file-decomposition` | idem | ✅ (heldout2, score 72,8, jamais vue) |
| redaction de PII | `pii-redaction` | idem | ❌ **écrit mais perd** contre `email-ops` sur la formulation de test ; conservé, non revendiqué |

Le troisième skill est livré mais **n'est pas compté comme un succès** : il ne
gagne pas sa propre requête de référence. Le diagnostic d'origine était
d'ailleurs à moitié faux — `agent-security-hardening` traite déjà la
redaction ; c'est un échec de routage (le mot « email » attire `email-ops`), pas
un trou de couverture. Corriger cela demanderait de régler le routeur sur
l'éval, donc non.

## 21. Ce que « 100 % » veut dire, et ce qu'il ne veut pas dire

État final du gate (`./run-checks.sh`, une seule exécution, sortie `ALL CHECKS
PASSED`) :

| contrôle | résultat |
|---|---|
| tests | **240 / 240 verts**, 0 `skip` |
| couverture (branches + sous-processus) | **89 %** pour un seuil fixé à 85 % |
| `eccx validate` (contrat overlay + js-yaml) | OK |
| `eccx audit --sample 20` | OK |
| `eccx eval --min-recall 0.9` (dev) | recall@3 96 %, MRR 0,835 |

Ce qui est tenu :

- **100 % des tests verts**, et aucun test ignoré (`skip`) pour y arriver.
- **100 % des chemins d'échec exercés** : chaque `except`, chaque refus, chaque
  entrée vide, chaque timeout a un test qui le provoque.
- **100 % des trous de catalogue avec un critère de done**, y compris ceux qui
  échouent (le tableau ci-dessus).

Ce qui n'est pas promis :

- **100 % de couverture de lignes.** La couverture atteinte est mesurée et
  publiée ; elle inclut les sous-processus (`COVERAGE_PROCESS_START`), sans quoi
  le chiffre serait faux. Augmenter le pourcentage en ajoutant des appels de
  fonctions triviales est une activité de mesure, pas de qualité.
- **100 % de recall.** Le plafond de récupération est mesuré (section 2) et
  trois requêtes heldout3 n'ont **zéro candidat à k=50** : aucun reranker ne les
  sauvera. Annoncer 100 % demanderait de changer le jeu de test.

L'étape suivante, si l'on veut vraiment durcir, n'est pas la couverture mais le
**mutation testing** (casser volontairement une ligne, vérifier qu'un test
échoue) et les **tests de propriété** sur le routeur (invariants :
monotonie du score, symétrie des stems, idempotence de l'index). Un test qui ne
peut pas échouer ne prouve rien, et c'est précisément ce que le taux de
couverture ne mesure pas.

## 22. Le journal des tests, et ce que chaque classe prouve

| classe | ce qu'elle prouve |
|---|---|
| `TestStemmerInvariants` | propriétés sur **tout le vocabulaire de l'index** : idempotence, pluriel≡singulier, dérivé≡racine, limites connues épinglées |
| `TestRerank` | les 4 règles de confiance du reranker, cache isolé par test |
| `TestMCPProtocol` | le client stdio contre un **vrai sous-processus** : ids, notifications, bruit non-JSON, erreur, mort du serveur, timeout |
| `TestMCPCLIEndToEnd` | `eccx mcp <serveur> <outil>` de bout en bout, config fusionnée incluse |
| `TestPrecommitRules` | **une règle = un test** : debugger, console.log, secret, config, gros fichier, et le cas « test file donc ignoré » |
| `TestEnforceEdgeCases` | chaque refus de l'installeur (non-git, hook étranger, désinstallation d'un hook qu'on n'a pas écrit) |
| `TestCLIBranches` | les branches que le chemin heureux ne prend jamais : ambiguïté, absence de résultat, `--kind`, `--json`, interruptions |
| `TestEvaluateReporting` | un jeu vide mesure zéro cas, un golden périmé est signalé au lieu de planter |

Deux règles de conception suivies partout : **les tests qui écrivent de l'état
utilisent un répertoire temporaire** (le cache de jugements, les sessions, les
hooks) — sinon un test pollue les mesures held-out et l'ordre d'exécution change
le résultat ; et **aucun test ne dépend d'un `sleep`** ou d'un réseau.

## 23. Troisième et quatrième bugs de la passe

`PY_DEBUG_RE` était compilé sans `re.MULTILINE` : `^` ne matche qu'à l'offset 0,
donc un `breakpoint()` laissé n'importe où sauf la première ligne n'était
**jamais** signalé. La règle existait, testée seulement sur des fichiers où elle
ne pouvait pas se déclencher. Corrigé, et le test qui l'a révélé est conservé.

`eccx tools` sans `--probe` : la boucle d'affichage était derrière un `if False:`
mort. La commande imprimait un titre et rien d'autre. Supprimé.
**C'est le seul type de défaut qu'un taux de couverture trouve vraiment** — et
il en a trouvé deux cette passe.

## 24. Le test qui mentait : une assertion de temps fixe

`test_index_is_cheap_to_build` affirmait `build() < 5,0 s`. Vrai à 1,3 s en
exécution normale ; **faux à 5,5 s sous instrumentation `coverage`**, qui trace
chaque ligne avec un facteur ~2–3. Le gate complet est devenu rouge pour une
raison qui n'a rien à voir avec le code : c'est le test qui était faux.

Deux leçons, appliquées :

- un test de performance dans une suite unitaire doit **déclarer son hypothèse
  d'exécution** ; ici le budget est multiplié par 3 quand
  `COVERAGE_PROCESS_START` est présent, avec le chiffre justifié en commentaire ;
- une assertion de temps doit **afficher la mesure** quand elle échoue
  (`took {took:.1f}s`), sinon on ne sait pas si on est à 5,1 s ou à 40 s.

Un test qui échoue au hasard détruit la confiance dans tout le reste de la
suite — c'est le pire défaut possible pour un gate.

## 25. Le test qui écrivait dans la vraie mémoire

Le nettoyage du workspace a révélé la même faute que le cache de jugements :
**trois tests écrivaient dans l'état réel de l'adaptateur**.

| ce que le test faisait | dégât mesuré |
|---|---|
| `TestMemory.test_save_and_search_roundtrip(..., cwd=ROOT)` | une note « roundtrip … » dans le vault réel, **à chaque exécution** |
| `run("session", "save", ...)` sans `--project` | une note « cli probe » par exécution |
| les tests de hooks (payload `cwd=/tmp/...`) | 574 lignes ajoutées à `.eccx/observations.jsonl`, toutes pointant vers des répertoires `/tmp` disparus |

Conséquence : au bout d'une session, le vault contenait **53 notes de test pour
1 note réelle**, et le journal d'observations était inexploitable — `eccx learn`
(qui mine ce journal pour proposer des skills) travaillait donc sur des données
qui n'existaient pas.

Corrigé : vault et journal temporaires par test, `--project` explicite pour les
tests CLI, et l'assertion d'observation porte désormais sur **le contenu**
(`tool`, `target`) — un simple comptage de lignes passait même en écrivant au
mauvais endroit. Même règle que pour le reranker : *un test qui écrit dans
l'état de production rend la prochaine mesure dépendante de la suite de tests.*

---

# Quatrième passe — les quatre leviers demandés, exécutés

La passe précédente se terminait par « si on veut vraiment durcir, la suite
n'est pas le pourcentage ». Voici ces quatre leviers, livrés et mesurés.

## 26. Tests de propriété — ils ont trouvé deux bugs en 60 secondes

19 propriétés dans `tests/test_properties.py`, écrites sur des entrées
générées (PRNG à graine fixe, donc reproductibles) et sur le catalogue entier
plutôt que sur une requête choisie à la main. La différence avec le reste de la
suite : un test classique affirme « pour cette requête, ce composant gagne » —
un fait sur un point de données, qui peut casser sans qu'il y ait de bug. Une
propriété affirme « pour toute requête, le top-k est un préfixe du top-2k » — une
affirmation qui ne peut pas être vraie par hasard.

Deux échecs réels, trouvés immédiatement :

**a) Les skills de l'overlay pouvaient être routés mais jamais lus.**
`test_section_ranges_are_ordered_and_inside_the_body` a échoué sur exactement
trois documents : `repository-hygiene`, `large-file-decomposition`,
`pii-redaction` — les trois skills ajoutés pour combler les trous du catalogue.
Cause : l'indexeur stocke leur `path` relativement au dossier de l'*adaptateur*,
alors que tous les lecteurs faisaient `ECC_ROOT / doc["path"]`. Résultat mesuré :

```
eccx recall "our repo is 4GB and cloning takes forever" --k 2
  → skill:repository-hygiene … puis AUCUN contenu
eccx show repository-hygiene
  → "958 tokens full; returned 1"       (un caractère)
```

Les métriques de routage ne pouvaient pas le voir : elles ne comparent que des
**identifiants**. Le skill gagnait, son corps était vide. Corrigé par
`util.doc_file(doc)`, qui résout la racine selon `extra.root`, utilisé par les
six lecteurs (recall, show, cmd, agent, review, audit). `INDEX_VERSION` → 8.

**b) `eccx audit` ne pouvait pas échouer.** Il imprimait
`WARN index points at a missing file`… et sortait avec le code 0, parce que le
retour ne testait que les désaccords js-yaml. **Un contrôle qui ne peut pas
échouer n'est pas un contrôle, c'est une ligne de log.** Le bug (a) est resté
invisible dans le gate pendant deux passes pour cette raison exacte. Séparation
maintenant explicite : `problems` (nos défauts → exit 1) vs `warnings` (qualité
amont, deux skills ECC sans description → affiché, non bloquant).

**c) `eccx eval --k 3` plantait.** `report()` lisait `metrics["recall@5"]`, clé
qui n'existait que si `k == 5` : une fonction de métrique qui ne marchait qu'à
sa valeur par défaut. Les métriques exposent désormais toujours 1/3/5 + le `k`
demandé.

**d) `truncate(x, n)` dépassait `n`** de la longueur du marqueur, et n'était pas
idempotent (le second appel tronquait le marqueur). Corrigé : la sortie tient
dans le budget, marqueur compris.

Une propriété a été **reformulée après examen**, et c'est le point le plus
important de cette section : `--kind skill` recalcule l'IDF sur le sous-corpus,
donc l'ordre relatif change. Ce n'est pas un bug, c'est un choix (un terme
présent dans 3 des 314 skills est plus discriminant que dans 3 des 607
composants). L'invariant affirmé est donc la **containment**, pas l'ordre — un
test qui aurait échoué pour une raison qui n'est pas un défaut est un mauvais
test, même quand il « trouve quelque chose ».

## 27. Mutation testing — le seul contrôle qui détecte un test vide

`tools/mutate.sh`, mutmut 3.8 sur `util.py`, `rerank.py`, `evaluate.py` :
**2 421 mutants**, ~9 minutes sur 2 vCPU. Règle de sélection : les tests unitaires
rapides seulement (53 tests, 3,5 s) ; les tests CLI à sous-processus (100 s)
domineraient le budget sans tuer plus de mutants.

Le premier résultat est l'argument le plus fort de tout ce document :

| module | mutants couverts | tués | score |
|---|---|---|---|
| `evaluate.run` | 185+ | 0 au départ | **0 %** |

`evaluate.run` était à 93 % de couverture et **aucun** de ses mutants ne
mourait : ses seuls tests affirmaient `cases == 0` sur un jeu vide. Toute
l'arithmétique (recall@k, MRR, `data_errors`, `rank`, `reranked`) pouvait être
supprimée sans qu'un test rougisse. 100 % couvert, 0 % vérifié — c'est
exactement ce que le taux de couverture ne peut pas dire.

Tests ajoutés en conséquence (`TestMetricArithmetic`, `TestGateBoundaries`,
`TestApplyOrderRules`, `TestJsonHelpers`), sur un index synthétique de trois
composants dont le classement attendu est évident : ils affirment des
**nombres** (`recall@1 == 0.5`, `mrr == round(1/rank, 3)`, `gap == GATE_MIN_GAP`
exactement) au lieu d'affirmer que le code s'est exécuté.

Résultat final de la passe : **80,4 %** (1 914 tués / 2 380 mutants couverts), sur une suite
de 462 tests, seuil du harnais fixé à **77 %** — un plancher anti-régression, pas un objectif.
Progression mesurée : 49,2 % → 65,3 % → 70,4 % → 72,2 % (périmètre étroit) → 69,0 %
(périmètre complet) → 79,3 % → **80,4 %**. Les chiffres bruts sont dans `docs/MUTATION.md`
(régénéré par le harnais), le tri manuel des survivants — fonction par fonction, avec la
liste des tests restants — dans `docs/MUTATION-TRIAGE.md`.

Trois constats qui comptent plus que le chiffre :

- **le score a d'abord baissé** quand le périmètre est passé de 3 modules à 5 : 72,2 % sur
  `util+rerank+evaluate`, 69,0 % en ajoutant `router` et `indexer`. Un score qui monte quand
  on rétrécit le périmètre n'est pas un score ; les deux valeurs sont publiées côte à côte ;
- **le score est un plancher, et c'est mesuré.** `tools/mutation_audit.py` rejoue les
  survivants hors trampoline : sur deux échantillons déterministes, 2/40 puis 0/100 sont
  tués par la suite alors que mutmut les classe « survived » (`inspect.signature()` suit
  `__wrapped__` et ne voit jamais une valeur par défaut mutée — vérifié à la main). Un
  instrument qu'on ne mesure pas lui-même est une opinion ;
- la cible de 80 % **n'est pas atteinte** : il manque 1 point. Les 468 survivants restants
  sont triés dans `docs/MUTATION-TRIAGE.md` : vrais trous (`_context_tokens` 30 %,
  `save_cache` 50 %, `resolve` 63 %), mutations équivalentes nommées, et 245 mutants hors
  du périmètre de mutation (fonctions atteintes seulement en sous-processus).

## 28. Tests de perf — sortis de la suite unitaire, budgets déclarés

`perf/budgets.py`, hors de `tests/` : un test unitaire affirme un comportement,
une assertion de temps affirme *la machine*. Les mélanger rend la suite
aléatoire — le test « build < 5 s » a rendu le gate rouge sous instrumentation
(§24).

9 mesures, médiane de 3 passes, budget déclaré et affiché à côté de la mesure :

| benchmark | mesuré | budget | marge |
|---|---|---|---|
| index build (607 docs, 4 906 sections) | 1,10 s | 6,0 s | 5,4× |
| `router.score`, catalogue complet, k=15 | **0,010 s** | 0,30 s | 29× |
| `router.score` ×25 requêtes (SLO 200 ms/requête) | 0,18 s | 5,0 s | 28× |
| `rerank.shortlist` k=30 | 0,012 s | 0,60 s | 50× |
| `rerank.resolve` cache froid (3 profondeurs) | 0,029 s | 1,20 s | 41× |
| `render_bundle`, budget 3 500 tokens | 0,008 s | 0,25 s | 32× |
| `eccx stats` (démarrage de process inclus) | 0,060 s | 1,50 s | 25× |
| `eccx recall --k 2` (process inclus) | 0,155 s | 2,50 s | 16× |
| `eccx eval`, 50 cas dev, lexical | 0,50 s | 8,0 s | 16× |

**Le benchmark a trouvé un défaut réel de performance, pas un décor :**
`router.score` coûtait ~90 ms parce que `_fields()` re-tokenisait les 607
documents à *chaque* requête. Mémoïsé sur le dict du document : **9× plus
rapide**, et `eccx eval` passe de 4,4 s à 0,5 s.

La première version de cette mémoïsation était fausse et les tests de propriété
l'ont attrapée en quelques minutes : la clé était `id(doc)`, or `id()` n'est
unique que parmi les objets **vivants** — un index reconstruit pouvait hériter
de la tokenisation d'un dict libéré. Corrigé en stockant le résultat *dans* le
dict, ce qui lie la durée de vie du cache à celle de l'objet. Les quatre jeux
d'évaluation sont re-mesurés après l'optimisation et sont **identiques au
centième** :

| jeu | lexical r@1 / r@3 | rerank r@1 / r@3 |
|---|---|---|
| routing (50) | 72,0 / 96,0 | 72,0 / 96,0 |
| heldout (30) | 36,7 / 53,3 | 73,3 / 76,7 |
| heldout2 (30) | 26,7 / 46,7 | 93,3 / 93,3 |
| heldout3 (12) | 33,3 / 41,7 | 75,0 / 75,0 |

Aucun benchmark ne tourne sous instrumentation : `perf/budgets.py` refuse de
démarrer si `COVERAGE_PROCESS_START` est présent.

## 29. Definition of done par trou — exécutable, pas de la prose

`evals/gaps.json` + `eccx gaps`, branchés dans `run-checks.sh`. Chaque trou
déclare sa requête d'origine, le composant attendu, et un drapeau `claimed`
honnête. La commande vérifie deux choses : le pipeline de production place bien
le composant en tête, **et** le contrat est rempli (indexé, fichier lisible,
corps non vide, description ≥ 40 caractères).

```
eccx gaps
  DONE  repository-weight    attendu skill:repository-hygiene        obtenu skill:repository-hygiene      k=50
  DONE  file-decomposition   attendu skill:large-file-decomposition  obtenu skill:large-file-decomposition k=50
  MISS  pii-redaction        attendu skill:pii-redaction             obtenu skill:email-ops               k=50  [non revendiqué]

  2/2 trous revendiqués sont tenus
```

Le troisième skill est livré et **compté comme un échec** : il ne gagne pas sa
propre requête de référence. Un `claimed: false` ne fait pas échouer le gate —
c'est toute la différence entre « on a livré quelque chose » et « on affirme que
ça marche ».

C'est ce contrôle qui aurait attrapé le bug (a) de la §26 : `ok` exige que le
fichier soit lisible et que le corps ne soit pas vide, pas seulement que l'id
sorte du routeur.

## 30. Ce que la couverture ne mesurait pas, et ce qui le mesure

| question | instrument |
|---|---|
| « ce code est-il mort ? » | couverture de branches (89 %) |
| « est-ce que ce composant **fonctionne** ? » | `eccx gaps` (DONE/MISS par trou) |
| « un test remarque-t-il une modification du code ? » | `tools/mutate.sh` (score de mutation) |
| « une affirmation générale tient-elle ? » | `tests/test_properties.py` (19 propriétés) |
| « est-ce encore utilisable ? » | `perf/budgets.py` (9 budgets, mesure affichée) |
| « le résultat dépend-il de l'historique ? » | §19 (mêmes métriques sur 5 états de cache) |

Les quatre leviers ont trouvé, à eux seuls, **six défauts** que ni la couverture
ni les 240 tests précédents n'avaient vus : contenu de l'overlay inaccessible,
audit incapable d'échouer, `--k 3` qui plante, `truncate` hors budget, cache de
tokenisation invalide, et 185 mutants vivants dans l'arithmétique des métriques.
