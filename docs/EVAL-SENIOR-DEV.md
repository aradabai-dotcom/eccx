# 20 tâches de dev senior — ce que la base sait faire, et ce qu'elle ne sait pas

Vous m'avez demandé de proposer les tâches au lieu d'attendre les vôtres.
Voici 20 requêtes qu'un développeur senior tape vraiment à un agent un lundi
matin, dans `evals/senior-dev.jsonl`.

Méthode : les requêtes et les réponses attendues ont été écrites **avant** de
regarder les classements, à partir du sens du catalogue. Les chiffres qui
suivent sont donc un test, pas une célébration.

---

## Les 20 tâches

| # | tâche | réponse attendue |
|---|---|---|
| 1 | production is down, the last deploy broke checkout, roll back now | `deployment-patterns` |
| 2 | this test passes locally and fails in CI one run out of four | `python-testing` |
| 3 | add a NOT NULL column to a 40-million-row table without downtime | `database-migrations` |
| 4 | review this API endpoint for auth and injection flaws before shipping | `security-review` |
| 5 | this single file is 600 lines and nobody dares touch it | `large-file-decomposition` |
| 6 | add a feature to a ten-year-old codebase I have never seen | `codebase-onboarding` |
| 7 | design the contract for a new public endpoint the mobile team consumes | `api-design` |
| 8 | this endpoint takes 4 seconds and the database says the query is fine | `latency-critical-systems` |
| 9 | our CI pipeline fails intermittently and I cannot tell which step | `github-ops` |
| 10 | upgrade a major dependency version, the changelog has breaking changes | `mcp-dependency-review` |
| 11 | review my colleague's pull request for correctness before it merges | `security-review` |
| 12 | record why we chose Kafka over RabbitMQ so nobody reopens the debate | `architecture-decision-records` |
| 13 | map this repository, I just joined and do not know where anything lives | `codebase-onboarding` |
| 14 | the retry logic double charges the customer when the network times out | `error-handling` |
| 15 | an access key got committed, what is the procedure | `security-scan` |
| 16 | our repo is 4GB and cloning takes forever | `repository-hygiene` |
| 17 | *mon déploiement de production a échoué cette nuit, revenir en arrière* | `deployment-patterns` |
| 18 | *ces tests échouent une fois sur quatre en intégration continue* | `python-testing` |
| 19 | *ajouter une colonne obligatoire à 40 M de lignes sans interrompre le service* | `database-migrations` |
| 20 | *relis la pull request de mon collègue avant fusion* | `security-review` |

Les quatre dernières sont les mêmes intentions que 1, 2, 3 et 11, **en
français**.

---

## Résultats mesurés

État après les trois chantiers (lexique, expansion, étage 2), catalogue complet :

| sous-ensemble | n | @1 | @3 | @20 (rappel) |
|---|---|---|---|---|
| toutes | 20 | **9 (45 %)** | 11 (55 %) | **16 (80 %)** |
| anglais seul | 16 | 7 (44 %) | 8 (50 %) | 13 (81 %) |
| **français seul** | 4 | **2 (50 %)** | 3 (75 %) | 3 (75 %) |
| toutes, profil `logiciel@1` | 20 | **11 (55 %)** | 12 (60 %) | **18 (90 %)** |

Point de départ au commit `e16635f` : catalogue complet 7 / 9 / 15 et profil
9 / 11 / 17 ; **français 0 / 1 / 2**. Après les trois chantiers : 9 / 11 / 16 et
profil **11 / 12 / 18** ; français **2 / 3 / 3**.

Le français passe donc de **0 à 2 sur 4** au rang 1, et le profil garde son
avantage (+2 au rang 1, +2 au rappel sur le catalogue complet). Ce dernier point
n'a tenu qu'après avoir repassé l'expansion en option : avec l'expansion active
par défaut, le profil tombait à 9/10/17 — c'est-à-dire qu'une « amélioration »
mesurée sur un jeu en dégradait une autre sur un autre.

---

## Ce qui a été corrigé, et ce que ça a rapporté

### 1. Un bug, avant toute traduction : les accents

`WORD_RE` est ASCII. `déploiement` se découpait en `ploiement`, et `précédente`
en `pr` + `dente`. Le fragment `pr`, de deux lettres, touchait le nom de
`review-pr` et pesait 5,0 — il faisait gagner le mauvais document sur toute
question française. Corriger `tokenize` (décomposition NFD, suppression des
diacritiques **avant** le motif) valait à lui seul une partie du gain.

C'est le rappel utile de ce chantier : **le défaut le plus coûteux n'était pas
celui qu'on cherchait.** J'ai construit un lexique pour un problème dont la
moitié était un bug de tokenisation.

### 2. Le lexique français→anglais (`eccxlib/lexique.py`)

135 mots et 35 locutions, appliqués **avant** la tokenisation. Le lexique ajoute,
il ne retire jamais : une requête anglaise en ressort identique, octet pour
octet. Vérifié par test sur quatre requêtes anglaises.

Quatre défauts trouvés en écrivant les tests, chacun invisible à l'œil :

| défaut | conséquence | correction |
|---|---|---|
| `rewrite` renvoyait la requête **d'origine** au lieu du texte réécrit | les 35 locutions étaient **inertes** depuis le début | renvoyer le texte replié quand une locution a matché |
| 22 entrées ne produisaient rien (11 vers `""`, 11 vers `fix`, mot vide) | le lexique affichait 157 entrées pour ~135 utiles | supprimées, et un test interdit d'en rajouter |
| formes fléchies absentes (`échouent`, `déployé`, `fusionnée`) | la traduction ne partait pas sur ces formes | génération des flexions depuis chaque entrée (-er, participe, pluriel) |
| `INDEX_VERSION` non incrémenté alors que `tokenize` changeait | index stocké à l'ancien découpage, requêtes au nouveau : deux tests de routage cassés qui passaient à HEAD | version 9 |

Le troisième point mérite une note : je n'ai pas écrit de racinisateur français.
Générer les flexions à partir des entrées, puis les fusionner dans une table
`LOOKUP`, donne le même résultat pour ce lexique-ci, en restant lisible et
testable. Un racinisateur aurait été plus élégant et plus fragile.

### 3. L'expansion sémantique (`eccxlib/expansion.py`)

Table de co-occurrence construite **depuis le catalogue** (PMI, seuil de 3
documents, 3 voisins maximum), pas un thésaurus écrit à la main : un thésaurus
rédigé par moi puis mesuré sur mes propres jeux serait de l'ajustement sur la
réponse.

Mesuré, décevant, et **dangereux sur certaines requêtes** — donc optionnel :

| jeu | sans expansion (défaut) | avec expansion |
|---|---|---|
| 20 tâches senior | 9 / 11 / 16 | 9 / 11 / **17** |
| `heldout` (30) | 11 / **16** / 24 | 11 / 15 / 24 |
| `heldout2` (30) | 8 / 14 / **27** | 8 / **15** / 26 |

Net zéro : un point de rappel gagné ici, perdu là. Mais le vrai problème est
ailleurs. Sur « security review of auth flow », la co-occurrence ajoutait
`cors`, `csrf`, `xss`, `password`, `laravel`, `middleware` — des mots qui
co-occurrent réellement avec « security » dans le catalogue. Résultat :
`laravel-security` passait devant `security-review`. **Le profil logiciel
perdait deux points de rang 1** tant que l'expansion était active par défaut.

C'est ce qui a fait échouer deux tests de routage qui passaient à HEAD. Le
mécanisme statistique est correct, l'effet est faux : la co-occurrence ne
distingue pas « mot du sujet » de « mot du voisinage ».

La construction a tout de même révélé un bug : `tokenize` laissait passer
`pipeline.` comme token, et la table se remplissait d'associations vers
`pipeline.`, `rollback.`, `release.`, qui ne correspondent à aucun document.

### 4. Le second étage : construit, mesuré, non activé

Cinquante configurations, trois jeux, aucune n'atteint la significativité.
Détail complet dans [`DEUXIEME-ETAGE.md`](DEUXIEME-ETAGE.md). En une ligne :
**les échecs restants ne sont pas des erreurs d'ordre, mais de rappel** — trois
des onze documents attendus ne sont même pas dans les 20 premiers, parce que
`github-ops` ne contient pas le mot « pipeline ».

---

## Les causes d'échec restantes

### 1. Le trou de vocabulaire — la vraie cause

`latency-critical-systems` ne contient nulle part « endpoint ». `github-ops` ne
contient pas « pipeline ». `security-scan` ne contient pas « committed key ».
**Aucun réordonnancement ne fait gagner un document qui ne partage aucun terme
avec la requête.** C'est la raison pour laquelle l'étage 2 ne peut pas payer :
le plafond du réordonnancement est à 85 %, et les 40 points qui manquent ne
sont pas dans la liste.

### 2. Un mot courant dans un nom bat un sens dans une description

| requête | ce que le routeur renvoie | pourquoi |
|---|---|---|
| this **endpoint** takes 4 **seconds**… | `scientific-db-pubmed-database` | « database » est dans le nom |
| the retry logic double **charges**… | `customs-trade-compliance` | « charges » (frais) est dans le nom |
| our **CI pipeline** fails… | `opensource-pipeline` | « pipeline » est dans le nom |

J'ai cru que le poids du nom (5,0) était le coupable. **Balayé de 2,5 à 5,0 : le
poids actuel est déjà l'optimum**, 5,0 donnant 9/11/17 contre 8/11/11 à 2,5. Le
nom domine parce qu'il est un signal fort, pas parce qu'il est surpondéré.
La piste « baisser le poids du nom » est donc morte ; il faut donner au
document pertinent les mots qui lui manquent.

---

## Ce qu'un senior ferait ensuite, par ordre de rentabilité

1. **Donner du vocabulaire au catalogue, pas au routeur.** Un champ `aliases`
   dans le frontmatter — `latency-critical-systems` déclarant `endpoint`,
   `p99`, `response time` — aurait un effet qu'aucun réglage n'a eu. C'est un
   travail de contenu, pas de code, et il est vérifiable : chaque alias ajouté
   se mesure sur ces 20 tâches.
2. **Des plongements multilingues.** `bge-small-en` est anglais seulement : une
   question française s'encode en bruit (document attendu aux rangs 113 et 127).
   Un modèle multilingue rendrait le lexique inutile pour les cas hors
   vocabulaire — c'est la seule voie qui traite le français *et* le trou de
   vocabulaire d'un coup. Coût : un modèle plus gros, et à mesurer, pas à croire.
3. **Ne pas rouvrir l'étage 2** avant que 1 ou 2 ait élevé le plafond : avec
   trois réponses absentes du top 20, un reranker n'a rien à réordonner.

---

## Les jeux scellés — et l'aveu qui va avec

Deux jeux écrits avant le début des chantiers, pour ne pas mesurer sur les
requêtes qui ont servi à construire : `evals/fr-heldout.jsonl` (12 requêtes
françaises) et `evals/en-heldout.jsonl` (16 requêtes anglaises reprenant les
mêmes intentions).

| jeu | n | @1 | @3 | @20 |
|---|---|---|---|---|
| français scellé | 12 | **6 (50 %)** | 7 (58 %) | 10 (83 %) |
| anglais scellé | 16 | **3 (19 %)** | 6 (38 %) | 12 (75 %) |

**Aveu.** J'avais prévu de ne les ouvrir qu'une fois, à la fin. Je les ai
mesurés plus tôt que prévu, en cherchant à savoir si le chemin sémantique déjà
livré (`score_hybrid`) changeait le classement. La mesure a été faite avec les
paramètres par défaut, sans réglage ensuite sur ces jeux — mais la garantie
« jamais regardé avant la fin » est tombée. Je le note ici plutôt que de laisser
croire à une discipline que je n'ai pas tenue jusqu'au bout.

**Ce que ces chiffres disent vraiment.** L'anglais scellé (19 %) est bien plus
faible que les tâches anglaises de `senior-dev` (44 %). Ce ne sont pas les mêmes
phrases : ces 16 requêtes sont traduites d'intentions françaises, et une
traduction littérale emploie un vocabulaire que le catalogue n'a pas. Autrement
dit, **le français n'est pas un cas particulier, c'est un cas général** : dès
qu'une requête sort du vocabulaire des fiches, le rang 1 s'effondre. Le lexique
traite le symptôme français ; la cause commune reste celle du trou de
vocabulaire.

---

## Refaire la mesure

```bash
python3 tools/eval_report.py --set evals/senior-dev.jsonl
python3 tools/eval_report.py --set evals/senior-dev.jsonl --profil logiciel
```

Le jeu est versionné. Si quelqu'un l'édite pour faire monter le score, le
`git diff` le montrera — c'est la seule protection honnête contre un banc
d'essai qu'on ajuste à ses résultats.
