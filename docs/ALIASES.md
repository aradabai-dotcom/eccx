# Alias : donner au catalogue les mots que les gens tapent

## Le problème, vérifié

`latency-critical-systems` décrit le suivi de p50/p95/p99, les caches, les
queues, les chemins critiques. Le mot **« endpoint »** y apparaît **zéro fois**
dans tout le fichier. Une question comme *« cet endpoint met 4 secondes et la
base dit que la requête est bonne »* ne peut donc pas l'atteindre : le document
ne partage aucun terme avec la question.

Ce n'est pas un problème de classement. Aucun réordonnancement ne fait gagner un
document qui n'est pas dans la liste. C'est un problème de **vocabulaire**, et la
correction est d'ajouter du vocabulaire au document.

## Pourquoi un registre, et pas un champ dans les 604 fichiers

Vous avez demandé un champ `aliases` dans le frontmatter. Le champ existe — mais
pas écrit dans `vendor/ecc/`, pour trois raisons concrètes :

1. `vendor/ecc/` est une base **vendue**, versionnée par empreinte
   (`BASE.sha256`) et resynchronisable (`tools/sync_upstream.sh`). Une
   resynchronisation écrase le fichier et perd l'alias.
2. Un diff de 604 fichiers n'est pas relisible. Une revue qui ne peut pas lire
   ne valide pas ; elle approuve.
3. Chaque alias a besoin d'une justification. Un commentaire dans un frontmatter
   YAML ne se valide pas en machine ; le registre, si.

Le champ est donc lu depuis le frontmatter quand on **possède** le fichier
(`skills-local/`, une fourche), et depuis `aliases/catalogue.json` pour la base
vendue. Une seule représentation en mémoire : `doc["aliases"]`.

## Le mécanisme

| | |
|---|---|
| champ indexé | `alias` |
| poids | **1,2** — sous la description (1,8), au-dessus des titres (0,55) |
| source | frontmatter (`aliases:`) + registre, recalculés à chaque chargement |
| stockage | `aliases_fm` (la revendication du fichier) est persisté ; `aliases` (l'effectif) ne l'est jamais |

Deux décisions méritent leur phrase :

**Le poids est sous celui de la description.** Un alias est une *affirmation*
qu'un document parle de quelque chose ; la description est le document qui le
dit lui-même. Une affirmation vaut moins qu'une déclaration. J'ai mesuré 3,5 :
ça rapportait un point de plus sur deux jeux, mais à ce poids un alias bat la
description, ce qui est faux dans les termes. Garder 1,2, c'est refuser un point
qui coûte la cohérence.

**L'effectif n'est jamais persisté.** La première version fusionnait avec la
valeur déjà dans le document : un alias retiré du registre survivait alors dans
tout index construit avant, sans aucun signal. Deux de mes propres tests se
contredisaient sur ce point — celui qui avait raison était le plus sévère. Un
index périmé ne doit pas pouvoir mentir sur ce que le registre dit aujourd'hui.

## Comment le contenu a été choisi

Règle posée **avant** de regarder quelles requêtes échouaient : un document
reçoit des alias s'il est **demandé au moins deux fois et raté au moins deux
fois** sur les cinq jeux de mesure. Treize documents en sont sortis. Ce n'est pas
une sélection au hasard, mais ce n'est pas non plus une sélection hors
échantillon — voir la section mesurée.

Chaque terme répond à une seule question : *comment un développeur
appellerait-il ceci, en dehors du vocabulaire de la fiche ?* Quelques exemples :

| fiche | la fiche dit | les gens disent |
|---|---|---|
| `error-handling` | retries, circuit breakers | `idempotency`, `double charge` |
| `agent-security-hardening` | untrusted content, runtime identifiers | `prompt injection`, `sandbox` |
| `security-review` | authentication, payment features | `auth bypass`, `vulnerability` |
| `code-tour` | fichiers `.tour`, CodeTour | `walk me through`, `guided tour` |

## Ce que les tests ont trouvé avant la livraison

**13 termes sur 43 ne servaient à rien.** Tous leurs tokens étaient déjà dans le
nom, la description ou les titres — que j'avais mal lus. Sans
`tools/alias_audit.py`, le registre aurait affiché 43 termes pour 30 utiles.
C'est exactement le défaut que je venais de corriger dans le lexique français
(22 entrées mortes), et je l'ai reproduit ici en une heure.

**3 termes sur 31 n'atteignaient pas leur propre fiche** interrogés seuls
(`github-ops` + « pipeline » : rang 30). Ce n'est pas un défaut du registre, c'est
une limite structurelle : un alias à 1,2 ne peut pas battre des noms à 5,0 qui
contiennent déjà le mot. « Pipeline » appartient à une douzaine de documents dont
c'est le nom — l'alias perd par construction. Règle adoptée : un terme qui ne
ramène pas sa fiche dans le **top 10** quand on l'interroge seul est retiré.

**Le résultat est un registre de 12 fiches et 28 termes.** La fiche `github-ops`
a été retirée entièrement : ses deux seuls termes échouaient, et garder un alias
décoratif est pire que ne rien avoir.

## Ce que ça rapporte, et ce que ça ne rapporte pas

Mesuré sur cinq jeux, registre actif ou vidé en mémoire, même index :

| jeu | sans alias | avec alias | Δ |
|---|---|---|---|
| **20 tâches de dev senior** | 9 / 11 / 16 | **10 / 12 / 18** | **+1 @1, +2 @20** |
| `heldout` (30) | 11 / 16 / 24 | 11 / 16 / 24 | 0 |
| `heldout2` (30) | 8 / 14 / 27 | 8 / 14 / 27 | 0 |
| français scellé (12) | 6 / 7 / 10 | 6 / 7 / 10 | 0 |
| anglais scellé (16) | 3 / 6 / 12 | 3 / **7** / 12 | +1 @3 |

**Aucune perte nulle part**, ce qui est le point important : les alias n'ont créé
aucun faux gagnant. Mais le gain est concentré sur le seul jeu qui a servi à
écrire le contenu, et c'est la signature de l'ajustement. Je ne le présente pas
comme une amélioration générale.

L'ablation le confirme : sur treize entrées, **trois seulement déplacent quelque
chose** (`error-handling` +1 @1, `verification-loop` +1 @20, `git-workflow`
+1 @20). Dix sont inertes sur les 108 requêtes mesurées.

Ce que ça veut dire : **le mécanisme est prouvé, le contenu est ajusté.** Le
mécanisme se vérifie sans jeu d'éval — 28 termes sur 28 ramènent leur fiche dans
le top 10 quand on les interroge seuls. Le contenu, lui, ne peut pas être validé
par 108 requêtes ; il demande du travail éditorial sur les 592 autres documents,
et ce travail se mesurera quand il sera fait, pas avant.

## Ce que ce n'est pas

Ce n'est pas une expansion automatique. Rien n'est deviné. Chaque entrée est
écrite par un humain avec un `why`, et `tools/alias_audit.py` refuse une entrée
sans justification.

Un thésaurus rédigé par moi puis mesuré sur mes propres jeux serait de
l'ajustement sur la réponse. La différence avec l'expansion par co-occurrence
(testée en PR #9, neutre), c'est que l'alias dit *« ce document traite de
ceci »* — une affirmation vérifiable par un relecteur — là où la co-occurrence
dit *« ces mots apparaissent ensemble »*, ce qui est vrai aussi pour un faux ami
(`security` et `csrf` co-occurrent, mais `csrf` n'est pas une revue de sécurité).

## Étendre le registre

```bash
# ajouter une entrée dans aliases/catalogue.json, puis :
python3 tools/alias_audit.py            # validité, effet, atteignabilité
python3 tools/alias_audit.py --check    # code de sortie, pour une porte
```

La porte `run-checks.sh` exécute `--check`. Un identifiant qui ne correspond plus
à un document fait donc échouer la suite : c'est la seule protection contre un
registre qui pourrit quand l'amont renomme une fiche.

---

## Annexe : deux attentes d'éval sont fausses

En cherchant les documents à enrichir, deux attentes de `evals/senior-dev.jsonl`
se sont révélées incompatibles avec le texte du catalogue. **Je ne les ai pas
modifiées** : l'instrument de mesure appartient à qui mesure, et changer un jeu
d'éval pour améliorer un score est précisément ce que ce dépôt combat. Voici la
preuve, à vous de trancher.

| requête | attendu | ce que dit la fiche attendue | ce qui décrit la tâche |
|---|---|---|---|
| « an access key got committed to the repository » | `skill:security-scan` | « Scan your **Claude Code configuration** (.claude/ directory) » | `agent:opensource-sanitizer` : « Scans for **leaked secrets**… » |
| « review my colleague's pull request for correctness » | `skill:security-review` | « when **adding authentication**, handling user input… **implementing payment** features » | `command:review-pr` : « **Comprehensive PR review** using specialized agents », au **rang 2** |

Les deux corrections n'ont pas le même statut, et c'est ce qui décide :

* **`security-scan` → `opensource-sanitizer` : aucun effet sur le score.** Les
  deux documents sont hors du top 60. La correction est donc démontrablement
  désintéressée — elle ne fait que rendre l'attente exacte.
* **`security-review` → `command:review-pr` : +2 au rang 3.** C'est pourquoi je
  ne l'applique pas. Un point gagné en réécrivant sa propre mesure n'est pas un
  point, c'est une dette d'honnêteté.

Ordre de grandeur si les deux étaient corrigées : 10 / 12 / 18 → 10 / 14 / 18.
Le rang 20 ne bouge pas — les deux tâches passaient déjà par une autre cible
alternative de leur liste `expect`.

À noter au passage : `code-review` et `review-pr` n'existent que comme
**commandes**, pas comme skills. Un `expect` qui vise `skill:code-review` ne peut
jamais être satisfait ; c'est la même classe de défaut que `skill:openapi`
détecté en PR #8, et le test qui valide l'existence des cibles ne l'a pas
attrapé ici parce que `skill:security-review`, lui, existe.
