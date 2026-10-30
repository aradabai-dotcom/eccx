# Provenance — base ECC vendue dans ce dépôt

Ce dossier n'est pas une dépendance : c'est **votre copie** du catalogue et du
code d'ECC. Elle est là pour être modifiée, amputée, étendue.

| | |
|---|---|
| Amont | https://github.com/affaan-m/ECC |
| Commit copié | `25278e7d7b6cf6e6a4e7a6c8e10f14ff22f0eb5b` (2026-10-26) |
| Licence | MIT — `Copyright (c) 2026 Affaan Mustafa`, voir `LICENSE` |
| Copié le | 2026-10-30 |

## Ce qui a été copié

`skills/` `agents/` `commands/` `rules/` `scripts/` `manifests/` `schemas/`
`contexts/` `tests/` `mcp-configs/`, plus `package.json`, `package-lock.json`,
`LICENSE`, `CONTRIBUTING.md`, `README.md` (notice d'origine conservée).

**1 831 fichiers, 22 Mo.** C'est le sous-ensemble qui fait tourner le routeur,
les validateurs et les tests d'ECC — vérifié : `routingEntries()` rend bien ses
292 entrées depuis cette copie.

## Ce qui n'a pas été copié, et pourquoi

| dossier | taille | raison |
|---|---|---|
| `assets/` | 23 Mo | images et captures de la page d'accueil. Zéro fonction. |
| `docs/` | 16 Mo | dont 8 Mo de traductions (ja-JP, zh-CN, es). Documentation de l'amont, remplaçable par la vôtre. |
| `pi/`, `ecc2/` | 4,1 Mo | projets annexes (Rust) livrés dans le même dépôt. |
| `docker/` | 1,7 Mo | images de déploiement, sans rapport avec le routage. |
| `examples/` | 384 Ko | exemples d'usage. |

Rien de tout cela n'est requis par le code. Pour récupérer un dossier :
`./tools/sync_upstream.sh --add assets`.

## Obligation MIT

La licence n'exige que de conserver la notice de copyright et le texte de la
licence — c'est `LICENSE`, présent ici. Elle **autorise** la modification, la
suppression et la redistribution, y compris sans publier vos changements.

Deux gestes d'honnêteté recommandés, non imposés : garder ce fichier à jour, et
dire dans votre README que la base vient d'ECC.

## Dépendances Node

5 paquets de production (`js-yaml`, `ajv`, `zod`, `@iarna/toml`, `sql.js`).
`node_modules/` n'est pas versionné. Une commande :

    ./tools/vendor_bootstrap.sh      # npm ci --omit=dev + vérification du routeur

Sans elle, le routeur JS et les validateurs d'ECC ne démarrent pas ; le CLI
Python `eccx`, lui, n'en a pas besoin.
