# eccx — router un symptôme vers le bon document

Un routeur pour gros corpus markdown : vous décrivez **ce qui se passe**, il
renvoie les 20 documents qui peuvent répondre — dans un budget de tokens dur.

```bash
pip install -e ".[dev]"
./eccx corpus build --dir ~/notes
./eccx --corpus ~/notes recall "le tunnel tombe chaque nuit vers trois heures" --k 5
```

Deux corpus sont pris en charge :

| corpus | comment |
|---|---|
| **le vôtre** (notes, décisions, doc interne) | `--corpus DIR` : taxonomie = dossiers, sections = titres, ids = chemins relatifs. Index dans `~/.eccx/`, jamais dans votre dossier. |
| **le catalogue ECC** (`affaan-m/ECC`) | clone dans `$ECC_ROOT` (`~/ECC` par défaut), puis `eccx index` |

- **532 tests**, couverture **88 %** mesurée en sous-processus compris, **80,4 %** de mutation
- **Shortlist à 80,5 % @20 pour 677 tokens**, contre 1 071 212 pour le catalogue entier
- `--budget` est une promesse dure, vérifiée par le gate

> **Les chiffres honnêtes.** `@1` vaut **34,9 %** sur 149 requêtes écrites avant
> toute mesure (13 gains / 3 pertes contre la référence, p = 0,021). Ce n'est pas
> « le routage est réglé » : la bonne réponse est *dans la shortlist* quatre fois
> sur cinq, ce qui n'est pas la même promesse. Sur un corpus personnel, la couche
> sémantique n'ajoute que +2,5 points @1 non significatifs : **le gain vient
> d'indexer le corps du document**, et le mode lexical est gratuit.
> Détail, échecs et corrections : [`docs/`](docs/).

---

## 0. Ce qui n'allait pas dans la v1

La première version « marchait » mais un senior l'aurait refusée. Les quatre
défauts, qui ont dicté la v2 :

| Défaut | Pourquoi c'est grave |
|---|---|
| Routage **non mesuré** | aucune idée de si 62 % ou 95 % des requêtes tombent juste ; toute « amélioration » est une opinion |
| `recall` injectait des **fichiers entiers** | sur un skill de 3 000 tokens, ~80 % hors sujet ; le budget était une illusion |
| Hooks **facultatifs** | `eccx fire` ne tourne que si l'agent y pense — donc jamais de façon fiable |
| Parseur YAML **maison, non validé** | 604 fichiers lus par du code non vérifié |

---

## 1. Découverte — index à deux niveaux

`eccxlib/indexer.py` indexe **604 documents et 4 882 sections (H2)** en 1,7 s
(index 1,4 Mo). Le texte des sections n'est pas copié : seulement
`(début, fin, coût, mots-clés)`, la source reste la seule vérité.

```bash
eccx stats     # 604 composants · 4 882 sections · 1 025 106 tokens au total
```

## 2. Reranker — le classement, mesuré sur données vierges

Écrire une requête et un routeur en même temps, c'est se noter sur ses propres
exercices. Le protocole retenu sépare les deux :

| jeu | rôle |
|---|---|
| `evals/routing.jsonl` (50) | réglage des seuils + garde-fou anti-régression |
| `evals/heldout.jsonl` (30) | écrit **avant** le reranker, ouvert **une fois** |

**Plafond mesuré d'abord** : à k=15, le bon composant n'est présent que pour
**76,7 %** des requêtes. Viser 85 % de recall@1 était donc impossible avant même
d'écrire le reranker — c'est le genre de chose qu'on découvre en mesurant.

| | recall@1 | recall@3 | MRR |
|---|---|---|---|
| lexical (held-out #1) | 33,3 % | 50,0 % | 0,422 |
| + rerank k=15 | 73,3 % | 76,7 % | 0,750 |
| lexical (held-out #2) | 20,0 % | 50,0 % | 0,348 |
| + rerank k=15 | 80,0 % | 80,0 % | 0,800 |
| **+ escalade k=30** | **90,0 %** | **90,0 %** | **0,900** |

Le reranker capture **27 des 27** requêtes récupérables sur le jeu #2 : 100 % du
plafond, à k=15 comme à k=30.

```bash
eccx rerank "make this function easier to read"   # émet ~400 tokens de candidats
eccx rerank --apply-file orders.json              # enregistre l'ordre du modèle
eccx recall "…" --rerank                          # consomme le jugement en cache
eccx eval --file evals/heldout2.jsonl --rerank    # mesure
eccx expand "…" --weights                         # inspection de Rocchio (opt-in)
```

**Escalade conditionnelle.** Le rerank à k=15 plafonne à 80 % sur held-out2.
Quand — et seulement quand — le jugement en cache dit `no_candidate`, la
récupération repart à k=30. Cela concerne 20 % des requêtes et fait passer le
score de 80 % à **90 %**, soit exactement le plafond du récupérateur.

Trois garanties, testées : un id absent du shortlist est **refusé** (pas de
réécriture rétroactive), un jugement est lié au **hash du jeu de candidats**
(ignoré après réindexation), et `[]` signifie « aucun candidat valable » —
compté comme échec de rappel, pas comme succès.

**Gate de confiance** réglé sur dev, jamais sur held-out : `(score ≥ 25, écart ≥ 0,30)`
saute 44 % des requêtes à 91 % de précision. Mesuré sur held-out, le gate seul ne
donne que 62 % : un score élevé n'est pas une preuve de correction, il sert à
économiser des tokens, pas à décider.

## 3. Routage — deux étages, une barre de qualité

**Étage 1 — documents** (`router.score`) : scoring par champs pondérés
(nom ≫ description ≫ titres), racinisation, expansion de synonymes normalisée par
le stemmer, couverture de requête, et quatre garde-fous :

| Garde-fou | Effet mesuré |
|---|---|
| Spécificité framework | `laravel-security` ne bat plus `security-review` sans Laravel |
| Intégration nommée | `x-api` ne détourne plus « rate limiting for an express api » |
| Contexte projet | `detect_packs()` lit `package.json`/`tsconfig`/`pyproject` |
| Feedback d'usage | `eccx feedback` réordonne les quasi-ex æquo (facteur borné ×0,7–1,5) |

**Étage 2 — sections** (`router.score_sections`) : on n'injecte que les blocs H2
qui répondent réellement, pas le fichier. C'est le gain le plus tangible :

```
v1 : skill:security-review → intro + « When to Activate »      1 209 tokens utiles à 40 %
v2 : skill:security-review → « Pre-Deployment Security Checklist » 572 tokens utiles à 90 %
```

**La barre** (`eccx eval`, 50 intentions réelles dans `evals/routing.jsonl`) :

```
recall@1  72.0%      recall@3  98.0%      recall@5 100.0%      MRR 0.838
```

Un `expect` pointant vers un composant disparu est signalé comme **erreur de
donnée** : une éval périmée est pire que pas d'éval. `run-checks.sh` échoue si
`recall@3 < 90 %` — c'est un garde-fou anti-régression, pas un rapport.

## 4. Hooks — distinguer ce qui est *conseillé* de ce qui est *imposé*

Le vrai correctif de la v1. L'agent n'a pas de runtime qui déclenche des hooks,
mais **git en est un**, et ses hooks se déclenchent seuls, pour tout le monde.

```bash
eccx install-hooks          # écrit .git/hooks/pre-commit
```

Ce qui est **imposé par git**, à chaque commit, sans discipline :

| Contrôle | Comportement | Preuve |
|---|---|---|
| `secret-scan` | commit **refusé** (clé AWS, tokens, clés privées…) | `git log` inchangé |
| `config-protection` | commit **refusé** si un `.eslintrc`/`prettier`/`ruff` est affaibli | exit 1 |
| `console-log` / `breakpoint()` | avertissement, commit accepté | exit 0 |
| fichier énorme | avertissement | — |

Ce qui reste **conseillé** (et déclaré comme tel dans `eccx manifest`) :
`gateguard` sur fichier existant, `doc-file-warning`, `governance-capture`,
`SessionStart`, `PreCompact`. Ils reproduisent le contrat Claude Code
(JSON sur stdin, **exit 2 = bloqué**) pour être utilisables tels quels.

## 5. MCP — un vrai client, borné et mis en cache

`initialize` → `tools/list` → `tools/call` en JSON-RPC sur stdio.

```bash
eccx tools --probe          # 8,1 s en parallèle, 0,056 s ensuite (cache 1 h)
eccx mcp ecc-memory-vault memory_save --args '{"title":"…"}'
```

**14 des 34 serveurs** configurés par ECC démarrent réellement ici (dont
`ecc-memory-vault`, `memory`, `sequential-thinking`, `github`, `firecrawl`).
Les autres sont marqués `unavailable` au lieu de faire attendre 2 minutes.

## 6. Mémoire — le vault officiel, pas une réécriture

`eccx session save|search|start` pilote le CLI Node d'ECC : ce que Claude Code
écrit, `eccx` le relit. Repli automatique sur un journal markdown si Node ou le
vault disparaît.

## 7. Hygiène : audit, comptabilité, synchronisation

```bash
eccx audit      # valide l'index ET compare mon parseur YAML à js-yaml
                # → "frontmatter parser agrees with js-yaml on the sample"
eccx report     # tokens injectés dans la journée vs catalogue
eccx sync       # git pull ECC + réindex + alerte si la version change
eccx review     # procédure ECC + le diff réel, $ARGUMENTS résolu
```

`ensure_ecc_deps()` réinstalle les dépendances npm d'ECC si le snapshot les a
supprimées (~3 s), ce qui est le seul état non persisté du montage.

---

## 8. Fidélité — ce qui est identique, adapté, ou impossible

| Capacité Claude Code | Ici | Détail |
|---|---|---|
| Découverte des skills | ✅ identique | 604 composants, 4 882 sections |
| Chargement à la demande | ✅ identique | `recall` / `show`, budget strict |
| Slash-commands + `$ARGUMENTS` | ✅ identique | `eccx cmd code-review 42` |
| Hooks | ✅ **imposés** (git) + conseillés | contrat exit 2 respecté |
| MCP client | ✅ identique | stdio JSON-RPC |
| Mémoire partagée | ✅ identique | même vault que Claude Code |
| Subagents | ⚠️ adapté | rendus en briefs, exécution séquentielle |
| `/plugin`, marketplace | ❌ impossible | appartient au parseur de Claude Code |
| Subagents **parallèles** | ❌ impossible | l'agent d'ici est mono-tour |

`eccx manifest` publie cette matrice **et les métriques** en JSON, pour que
l'outil ne puisse pas mentir sur lui-même.

---

## 9. Chiffres, avant / après

| | v1 | v2 |
|---|---|---|
| Pertinence mesurée | non mesurée | **recall@3 98 %** sur 50 intentions |
| Coût de la tâche démo | 2 229 tokens | **1 376 tokens** (−38 %) |
| Granularité injectée | fichier entier | **section H2** |
| Enforcement des hooks | bonne volonté | **git pre-commit** |
| Probe MCP (34 serveurs) | 163 s | **8,1 s** / 0,056 s en cache |
| Reranker cross-encoder | — | **testé, éliminé** : 5 gains / 51 pertes sur 50 requêtes aveugles (p < 0,0001) — il ramène au littéral et détruit le signal symptôme→pratique |
| Tests / couverture | 37 / non mesurée | **532 tests / couverture 88 %** (branches + sous-processus inclus) + 19 propriétés + **80,4 % de mutation** (2 639 mutants, plancher mesuré) |
| Parseur YAML | non validé | **croisé avec js-yaml** |
| Rappel annoncé | 72 % (jeu contaminé) | **36,7 % baseline réel / 73,3 % reranké** |
| Reranker | aucun | **+36,6 pts recall@1, 96 % du plafond** |
| Stabilité du cache | jugements perdus à chaque réindexation | **0 point perdu sur reconstruction complète** |

---

## 10. Aide-mémoire

```bash
eccx init · doctor · stats
eccx recall "<tâche>" [--k 4] [--budget 3500] [--kind skill,agent]
eccx show skill:security-review        # composant entier
eccx cmd code-review 42                # slash-command rendue
eccx agent security-reviewer --task "…"  # brief + skills routés
eccx rules [--packs typescript]
eccx review [--staged|--range HEAD~1]  # procédure + diff réel

eccx install-hooks                     # enforcement git
eccx precommit                         # exécuter les contrôles à la main
eccx fire <Event> [--tool X --file Y]  # hooks, contrat Claude Code

eccx rerank "<requête>" [--k 15]       # shortlist pour le modèle
eccx rerank --apply-file orders.json   # enregistrer un jugement
eccx recall "<tâche>" --rerank         # utiliser le jugement en cache
eccx eval [--file evals/heldout.jsonl] [--rerank]
eccx feedback skill:security-review [--bad]
eccx tools [--probe] [--refresh]       # MCP
eccx mcp <serveur> <outil> --args '{}'
eccx session save|search|start
eccx gaps                              # definition of done, par trou du catalogue
eccx audit · sync · report · manifest
```

## 10 ter. Quatre leviers de durcissement (et ce qu'ils ont trouvé)

| levier | commande | résultat |
|---|---|---|
| tests de propriété | `python3 -m unittest tests.test_properties` | 19 propriétés ; a trouvé que les 3 skills de l'overlay étaient routés **mais illisibles** |
| routage sur vos propres notes | — | **`eccx --corpus ~/notes`** : indexe n'importe quelle arborescence markdown (taxonomie = dossiers, sections = titres), 156 pages FastAPI indexées en 0,4 s, @1 **62,5 %** en lexical seul, **65,0 %** avec sections |
| routage sur requêtes jamais vues | 8 jeux, **224 requêtes** | recherche au niveau des **sections** (4 882 vecteurs) : **@1 25,3 → 33,3 / @3 44,4 → 52,5** sur **99 requêtes écrites avant toute mesure** (10 gains / 2 pertes **p = 0,039** ; 9/1 **p = 0,022**), **@20 75,4 → 79,0** sur 224 ; à k=20, **677 tokens** contre **1 071 212** pour le catalogue entier. Les plongements locaux `bge-small` sont fusionnés au score lexical ; le gain décisif vient de scorer chaque composant par **sa meilleure section H2**, pas par son résumé. Le plafond de récupération est à 84-87 % : le goulot est le classement, pas l'accès. L'effet des sections est un effet de **tête de classement** (à @20, p = 0,51) : 33 % @1 reste 33 %, pas 60 %. Détail et échecs : `docs/ROUTING-GENERALISATION.md` |
| barre de généralisation | `run-checks.sh` → `eval --file heldout5 --k 3 --min-recall 0.38` | dans le gate : la généralisation est vérifiée à chaque exécution, pas espérée |
| contrat de confiance | `eccx recall "…"` | **49 % @1 [IC95 35-63] sur 31 % des requêtes**, 18 % le reste. Signal = cosinus sémantique ; une première version fondée sur la marge a été **retirée** (64 % sur les données de réglage, 29 % hors échantillon) |
| budget de contexte | `TestBudgetIsAHardPromise` + `tools/budget_smoke.py` **dans le gate** | `--budget 400` émettait **1 983 tokens** (plancher de 250 par document) ; mesuré désormais sur la sortie réelle du CLI, 10 points, pire cas **1,00×** |
| mutation testing | `tools/mutate.sh` (~21 min, 2 639 mutants) + `tools/mutation_audit.py` | `indexer.build` était à **0 %** (252 mutants) malgré un test « l'index a 300 skills » ; `router.score` à 54 % ; score **69,0 % → 79,3 % → 80,4 %** après triage |
| definition of done | `eccx gaps` | 2/2 trous revendiqués tenus, 1 livré **non revendiqué** (assumé) |
| budgets de perf | `python3 perf/budgets.py` | a trouvé une re-tokenisation du catalogue à chaque requête : **9× plus rapide** après correction |

Un mot sur les deux mesures ajoutées au rapport d'éval : `escalated` disait
« on a élargi la recherche » et affichait **100 %** sur un cache vide, où rien
n'avait été jugé. `judged_deeper` répond à l'autre question — *le jugement
retenu a-t-il été fait plus profond que k* — et `expand_applied` à une
troisième : *l'expansion a-t-elle réellement ajouté des termes*
(**66 %** des requêtes du jeu de dev ; les autres n'ajoutent rien).

Les trois premiers sont dans `./run-checks.sh` ; la mutation et la perf en sont
exclues volontairement (9 min et sensible au timing) et se lancent à la main.

Vérifier l'ensemble : `./run-checks.sh` (tests + couverture + éval de routage).

## 10 bis. Troisième passe — les trous comblés, et la couverture

Trois manques réels du catalogue ont été comblés par un **overlay versionnable**
(`skills-local/`, trois skills) qui survit à `eccx sync`, avec le validateur de
contrat d'ECC (`eccx validate`, cross-checké contre js-yaml) :

| trou | skill | résultat sur un jeu écrit avant son existence |
|---|---|---|
| repo 4 Go, clone lent | `repository-hygiene` | top-1, formulation jamais vue |
| fichier de 600 lignes | `large-file-decomposition` | top-1, idem |
| PII dans les prompts | `pii-redaction` | **perd** contre `email-ops` — livré, non revendiqué |

Le troisième échec est un **échec de routage**, pas de couverture :
`agent-security-hardening` traite déjà la redaction. Le corriger demanderait de
régler le routeur sur l'éval de test.

Sur la demande « 100 % de couverture, 100 % de tests verts » : **240 tests,
tous verts, 89 % de couverture** branches et sous-processus inclus, gate à 85 %
dans `./run-checks.sh`. Mais la couverture de lignes n'est **pas** un objectif —
c'est un détecteur de code mort, et elle en a trouvé deux cette passe (boucle
morte derrière `if False:` dans `eccx tools`, `breakpoint()` jamais signalé
faute de `re.MULTILINE`), plus quatre bugs trouvés par les tests négatifs
(évaluation d'un jeu vide qui mesurait 50 cas, timeout MCP décoratif, `eccx learn`
qui plantait sur une ligne JSON valide, stemmer non idempotent). Détail, chiffres
et limites : `docs/QUALITY.md` §16–23.

## 11. Limites assumées

1. **Pas de subagents parallèles** — contrainte du runtime, pas un choix.
2. **Il reste 3 requêtes heldout3 sans aucun candidat, même à k=50**
   (`security-scan`/CVE, `error-handling`/fail loudly, `review-pr`/PRs non
   relues) : lacune de vocabulaire du catalogue, non corrigée à dessein pour ne
   pas régler le routeur sur le jeu de test. Le plafond de récupération est
   publié à chaque exécution plutôt que masqué.
3. **Rocchio n'a pas marché** ici — mesuré négatif sur deux jeux, cause
   diagnostiquée (les termes des requêtes sont absents des documents cibles).
   Gardé en option, désactivé par défaut.
3. **Les hooks git couvrent le commit, pas l'écriture de fichier.** Un agent peut
   encore écrire du code bancal ; il ne peut plus le *commiter* silencieusement.
4. **Le clone ECC pèse 104 Mo** dans le workspace.
