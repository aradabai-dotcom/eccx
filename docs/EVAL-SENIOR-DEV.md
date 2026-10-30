# 20 tâches de dev senior — ce que la base sait faire, et ce qu'elle ne sait pas

Vous m'avez demandé de proposer les tâches au lieu d'attendre les vôtres.
Voici 20 requêtes qu'un développeur senior tape vraiment à un agent un lundi
matin, dans `evals/senior-dev.jsonl`.

Méthode : les requêtes et les réponses attendues ont été écrites **avant** de
regarder les classements, à partir du sens du catalogue. Les chiffres qui
suivent sont donc un test, pas une célébration. Ils sont mauvais.

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

| sous-ensemble | n | @1 | @3 | @20 (rappel) |
|---|---|---|---|---|
| toutes, catalogue complet | 20 | **7 (35 %)** | 9 (45 %) | 15 (75 %) |
| toutes, profil `logiciel@1` | 20 | **9 (45 %)** | 11 (55 %) | 17 (85 %) |
| anglais seul, complet | 16 | 7 (44 %) | 8 (50 %) | 13 (81 %) |
| **français seul, complet** | 4 | **0 (0 %)** | 1 (25 %) | 2 (50 %) |
| français seul, profil | 4 | **0 (0 %)** | 2 (50 %) | 2 (50 %) |

À comparer aux 60 requêtes de `heldout` : 19/60 (32 %). Sur des tâches
réalistes, on est au même niveau — **et le profil logiciel apporte ici +2 au
rang 1 et +2 au rappel**, ce qu'il ne faisait pas sur `heldout`. Un jeu
représentatif compte plus qu'un grand jeu artificiel.

---

## Pourquoi ça échoue — trois causes, pas une

### 1. Le français ne passe pas du tout (0/4)

Le catalogue est en anglais et le routeur n'a aucune capacité interlingue.
« mon déploiement de production a échoué » renvoie `review-pr` : un seul mot
(« production ») survit au tokeniseur, et il ne mène nulle part.

Pour un utilisateur qui travaille en français — Casablanca, équipes
francophones — **c'est le défaut numéro un de tout l'outil**, bien avant les
53 points de rang 1 dont je parlais au tour précédent. Aucune retouche de poids
ne le corrigera : il faut soit un lexique de traduction des termes techniques,
soit des embeddings multilingues.

### 2. Un mot courant dans un nom bat un sens dans une description

| requête | ce que le routeur renvoie | pourquoi |
|---|---|---|
| this **endpoint** takes 4 **seconds**… | `scientific-db-pubmed-database` | « database » est dans le nom |
| our **CI pipeline** fails… | `opensource-pipeline` | « pipeline » est dans le nom |
| the retry logic double **charges**… | `customs-trade-compliance` | « charges » (frais) est dans le nom |
| design the **contract**… | `dev-team` | aucun terme fort ne départage |

Le poids du nom (5,0) plus un IDF calculé sur 604 documents laissent gagner un
nom qui contient un mot de la requête, même quand le sens est ailleurs.

### 3. Le trou de vocabulaire — la vraie cause des échecs restants

`latency-critical-systems` ne contient nulle part le mot « endpoint ».
`github-ops` ne contient pas « pipeline ». **Aucun réordonnancement ne peut
faire gagner un document qui ne partage aucun terme avec la requête.**

C'est ça, les 53 points : pas un problème de classement, un problème de
vocabulaire. La réponse est un étage d'expansion (synonymes) ou de plongements,
pas un réglage de poids.

---

## Ce que j'ai essayé, et ce que ça a donné

| tentative | résultat |
|---|---|
| retirer `-ion` du racinisateur (`production` → `product`, un **vrai autre mot**) | +1 au rang 1 sur les 20 tâches, 0 sur les 60 |
| bonus si un mot de la requête est dans le nom | −1 (18/60) |
| indexer le corps en plus de la description | −4,6 points (mesuré lors du développement) |
| élaguer le catalogue de 250 skills | +9 au rang 1, rappel inchangé — artefact |
| profil `logiciel@1` | +2 au rang 1, +2 au rappel sur ces 20 tâches |

Le bug `production → product` est réel et mérite d'être corrigé (une panne en
production ne doit pas mener à `product-capability`), mais son gain mesuré est
d'un point : ce n'est pas lui qui explique le 35 %.

---

## Ce qu'un senior ferait ensuite, par ordre de rentabilité

1. **Le français.** 0/4 aujourd'hui. Un lexique technique français→anglais
   (`déploiement`, `sauvegarde`, `revue de code`, `migration`, `incident`…)
   coûte une journée et débloque un utilisateur entier. À mesurer sur les 4
   requêtes françaises ci-dessus, puis sur 20 autres.
2. **L'expansion sémantique** pour le trou de vocabulaire (« endpoint » →
   `latency`, `performance`), mesurée sur ces 20 tâches, pas sur `heldout`.
3. **Un second étage discriminatif** sur le top-5 — mais seulement quand 1 et 2
   auront élevé le plafond, sinon il classera mieux des candidats absents.

---

## Refaire la mesure

```bash
python3 tools/eval_report.py --set evals/senior-dev.jsonl
python3 tools/eval_report.py --set evals/senior-dev.jsonl --profil logiciel
```

Le jeu est versionné. Si quelqu'un l'édite pour faire monter le score, le
`git diff` le montrera — c'est la seule protection honnête contre un banc
d'essai qu'on ajuste à ses résultats.
