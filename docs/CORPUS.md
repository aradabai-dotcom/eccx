# Router votre propre matière

## Ce que ça fait

```bash
./eccx corpus build --dir ~/notes        # indexe tout le markdown du dossier
./eccx corpus stats --dir ~/notes        # ce qui est réellement indexé
./eccx --corpus ~/notes recall "le tunnel tombe chaque nuit" --k 5
./eccx --corpus ~/notes eval --file mes-requetes.jsonl --k 20 --json
```

`--corpus` vaut pour toutes les commandes : `recall`, `context`, `eval`,
`vectors`, `show`. L'index et les vecteurs vont dans `~/.eccx/<slug-du-dossier>/`,
**jamais** dans le dossier indexé — on n'écrit pas dans un dossier que vous
éditez, synchronisez ou versionnez.

## Comment le corpus est lu

| décision | règle | pourquoi |
|---|---|---|
| taxonomie | premier segment du chemin | c'est la seule structure que l'auteur a déclarée exprès |
| identifiant | chemin relatif sans extension | stable entre rebuilds ; renommer casse l'id, et c'est honnête |
| découpage | le niveau de titre le plus haut utilisé **au moins deux fois** | un `##` isolé sous un `#` est un accident, pas une structure |
| titres dans un bloc de code | ignorés | sinon un exemple yaml devient un chapitre |
| texte | jamais copié, seulement des offsets | éditer une note n'invalide pas l'index par le contenu |
| fichier sans titre | signalé dans `stats`, pas caché | il ne sera trouvable qu'en similarité de document |

## Mesure sur un corpus indépendant

FastAPI, 156 pages de documentation, 986 sections — écrites par d'autres, pour
d'autres raisons. 40 requêtes écrites **avant** la mesure
(`evals/corpus-fastapi.jsonl`). Corpus reproductible : `tools/fetch_corpus.sh`.

| configuration | @1 | @3 | @20 | coût |
|---|---|---|---|---|
| lexical seul | 62,5 % | 75,0 % | 87,5 % | 0 modèle, index 340 Ko, build instantané |
| + sémantique (doc) | 57,5 % | 75,0 % | 97,5 % | +130 Mo de modèle, +250 Mo RSS |
| + sections | **65,0 %** | **80,0 %** | 97,5 % | +1,5 Mo d'index, build 1 min |

Apparié sur les 40 requêtes : sections contre lexical, 4 gains / 3 pertes
**p = 1,0**. Autrement dit : **sur ce corpus, tout l'appareillage sémantique
n'achète que +2,5 points @1, non significatifs.**

### Pourquoi ce n'est pas la même histoire que sur ECC

Sur le catalogue ECC, les sections valaient +7 points sur 149 requêtes aveugles
(p = 0,021). La différence tient à une seule chose : **chez ECC, le texte est
dans le corps et n'était pas indexé lexicalement** ; le résumé (`description`)
est une ligne écrite à la main. Sur un corpus personnel, le corps est du texte
ordinaire — et dès qu'on l'indexe lexicalement, la similarité sémantique
n'ajoute presque rien.

C'est une conclusion désagréable pour l'outil, et utile pour vous : **le gain
vient d'indexer le corps, pas du modèle**. Le modèle n'est qu'un moyen de le
faire quand le corps est invisible.

### Correction d'une annonce faite en séance

À 12 h 34, j'ai annoncé « +15 points @1 grâce aux sections » sur ce même
corpus. C'était faux : l'armée lexicale de comparaison n'indexait pas le corps
du tout, donc elle ne pouvait rien trouver, et n'importe quel ajout aurait
semblé miraculeux. Le chiffre correct est +2,5 points, p = 1,0. Quatrième
défaut de mesure de la session, tous de la même famille : **la référence
comparée n'était pas le produit**.

## Le protocole qui protège vos chiffres

Un routeur mesuré sur des requêtes écrites après avoir vu les résultats ne vaut
rien. Celui-ci a coûté quatre corrections.

1. **Indexer d'abord**, sans écrire de requêtes.
2. **Écrire 60 requêtes** que vous poseriez vraiment, en une passe, dans
   `mes-requetes.jsonl` — une par ligne :
   ```json
   {"q": "le tunnel tombe chaque nuit vers trois heures", "expect": ["projets/vpn"]}
   ```
   `expect` accepte l'identifiant complet (`projets/vpn`) ou qualifié
   (`projets:projets/vpn`), et plusieurs cibles acceptables.
3. **Mesurer une fois**, avec `--json`, et noter les profondeurs.
4. **Ne rien régler** avant d'avoir comparé à votre recherche actuelle
   (`grep`, `fzf`, l'explorateur). Le seul critère qui compte : est-ce plus
   rapide d'arriver à la bonne note ?

## Ce qu'il faut regarder avant de croire au résultat

`eccx corpus stats --dir ~/notes` :

- **`without sections`** proche de 0. Sinon, vos notes n'ont pas de structure et
  le découpage ne fait rien : mettez-les en ordre, ou acceptez un routeur au
  niveau du document.
- **`median doc tokens`** entre 300 et 2 000. En dessous, `grep` gagne. Au
  dessus, vos documents sont trop gros pour qu'un titre suffise à les résumer.
- **moins de ~200 documents** : `grep` gagne encore. C'est un outil pour gros
  corpus ; je préfère l'écrire que vous vendre un routeur sur 40 fiches.

## Ce qui reste à construire

- détection de langue : le tokenizer est anglais (stemming Porter), il dégrade
  proprement sur du français mais sans rabattement — mesuré seulement par
  accident ici.
- les liens entre documents (`[[wiki]]`, références) ne sont pas suivis.
- pas encore d'index incrémental : un fichier ajouté impose `corpus build`
  (~4 s pour 2 500 documents, ~1 min avec les vecteurs).
