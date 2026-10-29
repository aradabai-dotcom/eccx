# Mutation testing — journal

Généré par `tools/mutate.sh`, 2026-10-28T20:32:55Z.

| mesure | valeur |
|---|---|
| mutants générés | 2639 |
| tués | 1914 |
| survivants | 463 |
| timeout | 3 |
| sans test (ligne non couverte) | 259 |
| **score de mutation** | **80.4 %** |
| seuil du harnais | 77 % |

Score = tués / (tués + survivants + timeouts). Les mutants « sans test »
sont exclus : ils mesurent la couverture, déjà gardée par le gate de
couverture, et les compter deux fois permettrait de maquiller le score.

## Survivants par fonction

```
     76 evaluate.x_run
     56 indexer.x_build
     41 router.x_render_bundle
     39 router.x_score
     38 rerank.x_resolve
     37 router.x_detect_packs
     13 router.x_suggest_rules
     13 rerank.x__project
     12 rerank.x_load_cache
     12 evaluate.x_report
     11 util.x__stem_once
     10 rerank.x_gate
     10 rerank.x_apply_order
     10 indexer.x_split_sections
      9 rerank.x_coverage
      7 util.x_tokenize
      7 router.x__context_tokens
      7 rerank.x__apply
      6 util.x_save_json
      6 router.x__fields
```

## Comment lire ce chiffre

Un score de 100 % est un objectif de mauvaise foi : il y a toujours des
mutations équivalentes (changer `<` en `<=` sur une borne que les données
ne touchent jamais). Ce qui compte :

1. le score **ne baisse pas** d'une passe à l'autre ;
2. chaque survivant examiné est classé *équivalent* (justifié) ou *trou réel*
   (corrigé par un test) — jamais ignoré.
