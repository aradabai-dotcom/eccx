# La base est à vous — comment la modifier sans se tromper

`vendor/ecc/` contient le catalogue et le code d'ECC, copiés une fois
(commit `25278e7`, 2026-10-26), et **c'est votre copie**. Rien ici n'est une
dépendance : vous pouvez modifier, supprimer, ajouter — MIT le permet, et le
dépôt vous appartient.

Le seul fichier à ne pas effacer : `vendor/ecc/LICENSE`. La licence MIT exige de
garder la notice de copyright.

---

## Ce que vous pouvez toucher, et ce que ça casse

| ce que vous modifiez | conséquence |
|---|---|
| un `SKILL.md` (corps) | change ce qui est injecté ; le routage ne bouge pas (il lit le `description:` du frontmatter) |
| un `description:` de frontmatter | **change le routage** — c'est le seul champ que le routeur voit |
| supprimer une skill entière | retire un candidat : gain si elle n'était jamais la bonne réponse, perte sinon |
| `scripts/lib/context-selection.js` | change la sélection et le budget d'injection d'ECC — attention au reçu lié par digest |
| ajouter une skill dans `skills-local/` | elle est indexée en plus, sans toucher à la base |

Après toute modification : `python3 ./eccx index` (reconstruit, 603 documents en
~2 s).

---

## La règle de suppression, mesurée

Supprimer du catalogue n'est pas neutre : mesuré sur les 60 requêtes aveugles,
en préservant les bonnes réponses.

| catalogue | @1 |
|---|---|
| complet — 314 skills, 603 documents | **19/60 (32 %)** |
| − 50 skills (au hasard) | 21,0/60 (35 %) |
| − 150 skills | 24,8/60 (41 %) |
| − 250 skills (il en reste 64) | **30,0/60 (50 %)** |
| − 150 skills **sans** protéger les bonnes réponses | 21/60 (35 %) |
| les bonnes réponses supprimées | **3/60 (5 %)** |

Deux lectures, toutes les deux vraies :

1. **Le bruit coûte cher.** Chaque skill inutile est un concurrent qui peut
   passer devant. Retirer 250 skills sur 314 fait passer le rang 1 de 32 % à
   50 %, sans rien améliorer d'autre. À catalogue constant, c'est le levier le
   plus puissant mesuré dans tout ce dépôt.
2. **Supprimer la bonne réponse détruit tout** : 3/60. Le gain n'existe que
   dans la zone où ce qu'on enlève n'aurait jamais été la réponse.

### Comment supprimer sans se tromper

1. Listez ce que vous ne faites jamais. Le tri par domaine marche mieux que le
   tri fin : `marketing`, `legal`, `healthcare`, `finance` partent en bloc.
2. **Avant de supprimer**, vérifiez que vos requêtes types ne pointent pas
   dessus : `./eccx recall "votre tâche" --k 5` sur les 20 tâches que vous faites
   vraiment.
3. Supprimez, réindexez, rejouez ces 20 requêtes. Si une requête perd son bon
   document, la skill était utile — remettez-la.
4. Gardez la trace de ce que vous retirez dans ce fichier : un mois plus tard,
   « pourquoi cette skill n'est plus là ? » n'a pas de réponse autrement.

Le côté réversible : la base d'origine se retélécharge en une commande
(`./tools/fetch_ecc.sh`, clone épinglé dans `ecc-pin.txt`), donc rien n'est
définitif.

---

## Ce que vous ne gagnez pas en supprimant

- **La vitesse** : l'index complet se charge en 15 ms. Retirer 250 skills ne
  rend pas l'outil sensiblement plus rapide — c'est le routage qui gagne, pas
  la latence.
- **Les tokens** : le budget d'injection reste plafonné à ce que vous demandez.
  Supprimer réduit les candidats concurrents, pas la taille de ce qui est
  envoyé. Le gain de tokens vient du découpage en sections, pas de l'élagage.

---

## Ajouter plutôt que supprimer

`skills-local/` est fait pour ça : trois skills y vivent déjà (`pii-redaction`,
`repository-hygiene`, `large-file-decomposition`), écrites pour combler des
trous du catalogue. Elles sont indexées avec les autres et `git pull` sur
l'amont ne peut pas les écraser.

Format : un dossier, un `SKILL.md`, un frontmatter `name` + `description`. La
`description` est ce que le routeur lit — c'est elle qu'il faut soigner, pas le
titre.

---

## Refaire les chiffres de ce document

```bash
python3 tools/prune_experiment.py       # le tableau ci-dessus
python3 tools/token_budget_experiment.py  # budget de tokens à plafond égal
```
