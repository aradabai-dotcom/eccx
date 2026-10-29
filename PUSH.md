# Mettre `eccx` sur votre dépôt

## Ce qui est prêt

Un dépôt git autonome, deux commits, 58 fichiers, **238 Ko** :

```
/home/user/ecc-adapter.bundle      ← le dépôt entier, historique compris
```

`ecc-adapter.bundle` est un fichier unique et **autonome** : il contient les
commits, les arbres et l'historique. Il ne dépend d'aucun service et ne
demande aucun identifiant.

Vérifié : clone à froid → `corpus build` → `recall` sans catalogue ECC, avec
`numpy` seul. C'est le chemin que suivra votre premier utilisateur.

## Trois défauts corrigés avant l'envoi

- `.eccx/`, `mutants/` et `.coverage` étaient sur le point d'être commités :
  18 Mo d'état d'exécution, dont `observations.jsonl` qui contient les requêtes
  réellement tapées. `.gitignore` les exclut.
- `.ecc/` (mémoire écrite par l'outil) est exclu aussi.
- La CI **échouait à chaque push** : elle lançait `eccx vectors` avant
  `eccx index`, n'installait jamais `pytest`, et ne clonait pas le catalogue
  contre lequel elle teste. Corrigé, avec le vrai temps du job sémantique
  (9 minutes, pas les 40 secondes du commentaire écrit avant les sections).

---

## Voie A — vous poussez, je ne vois aucun identifiant (recommandé)

1. Créez un dépôt **vide** sur GitHub (pas de README, pas de LICENSE).
2. Téléchargez `ecc-adapter.bundle` depuis le workspace.
3. Sur votre machine :

```bash
git clone ecc-adapter.bundle eccx
cd eccx
git remote add origin https://github.com/VOTRE_COMPTE/VOTRE_DEPOT.git
git branch -M main
git push -u origin main
```

À la ligne `git remote add`, remplacez `VOTRE_COMPTE/VOTRE_DEPOT` par le
chemin de votre dépôt. Rien d'autre à changer.

## Voie B — je pousse depuis ici

Il me faut deux choses :

1. **L'URL du dépôt** : `https://github.com/VOTRE_COMPTE/VOTRE_DEPOT.git`
2. **Un jeton d'accès** (obligatoire : il n'y a aucun identifiant sur cette
   machine, et je n'ai pas de connecteur GitHub).

Création du jeton, à limiter au strict minimum :

- GitHub → Settings → Developer settings → **Personal access tokens →
  Fine-grained tokens** → *Generate new token*
- **Repository access** : *Only select repositories* → votre dépôt uniquement
- **Permissions** : *Contents* → **Read and write**. Rien d'autre.
- **Expiration** : 7 jours

Puis, si vous choisissez cette voie :

```bash
git remote add origin https://github.com/VOTRE_COMPTE/VOTRE_DEPOT.git
git push https://x-access-token:LE_JETON@github.com/VOTRE_COMPTE/VOTRE_DEPOT.git main
```

**Ce que ça implique, dit franchement** : un jeton collé dans le chat reste dans
l'historique de la conversation. Si vous prenez cette voie, révoquez le jeton
dès que le `push` est passé (Settings → le jeton → *Revoke*). Je ne peux pas
vous promettre de l'effacer après coup.

## Voie C — vous repartez des fichiers

Si vous préférez ne pas passer par un bundle :

```bash
# dans un dossier vide
git init -b main
# copiez le contenu de /home/user/ecc-adapter (sauf .eccx/ et mutants/)
git add -A && git commit -m "eccx"
git remote add origin https://github.com/VOTRE_COMPTE/VOTRE_DEPOT.git
git push -u origin main
```

---

## Après le push, ce qui se passe tout seul

`.github/workflows/checks.yml` tourne sur chaque push :

| job | durée | bloque ? |
|---|---|---|
| checks (500 tests, couverture, 7 barres scellées, smoke corpus) | ~15 min | oui |
| perf (budgets de latence) | ~2 min | non, `continue-on-error` |
| mutation (80,4 %) | ~90 min | seulement manuel ou planifié |

Le job `checks` clone `affaan-m/ECC` dans `$HOME/ECC` et construit les
vecteurs : comptez 15 minutes pour le premier run, pas 2. Ensuite, `actions/cache`
n'est pas encore branché sur `.eccx/vectors.npy` — c'est le premier gain à
prendre si vous voulez un badge vert en 3 minutes.

## Ce que le dépôt ne contient pas, volontairement

- **Le catalogue ECC** : lu depuis `$ECC_ROOT`, jamais recopié (MIT, mais ce
  n'est pas à moi de le redistribuer).
- **La doc FastAPI** : `tools/fetch_corpus.sh` la retélécharge.
- **Les vecteurs et l'index** : régénérés par `eccx index` puis `eccx vectors`.
- **Aucune donnée d'exécution** : ni requêtes tapées, ni sessions, ni mémoire.
