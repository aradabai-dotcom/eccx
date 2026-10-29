# Pourquoi ce fichier n'est pas dans `.github/workflows/`

GitHub refuse tout push qui crée ou modifie `.github/workflows/*` s'il n'a pas
le scope `workflow`. Le rafraîchissement de ce scope a échoué trois fois de
suite sur un `connection reset` pendant l'échange du jeton device-flow (le point
d'échange répond 404 puis 200 d'un appel à l'autre : coupure intermittente du
réseau de la sandbox, pas de GitHub).

Le fichier est donc versionné ici, à un `cp` de sa place :

```bash
mkdir -p .github/workflows
cp ci/checks.yml .github/workflows/checks.yml
git add .github && git commit -m "ci: enable the gate" && git push
```

C'est la seule chose qui manque pour que le badge tourne. Le produit n'en dépend
pas : `run-checks.sh` et `tools/` sont les barrières, le YAML ne fait que les
planifier.

## Ce que fait le job

| job | durée | bloque ? |
|---|---|---|
| `checks` | ~15 min | oui — 503 tests, couverture, 8 barres scellées, smoke corpus |
| `perf` | ~2 min | non (`continue-on-error`) |
| `mutation` | ~90 min | manuel ou planifié seulement |

Le premier run est long parce qu'il clone `affaan-m/ECC` et construit les
vecteurs (607 documents + 4 906 sections). `actions/cache` sur `.eccx/` n'est
pas encore branché : c'est le premier gain si vous voulez un badge vert en
3 minutes.
