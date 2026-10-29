# Routage : mesurer la généralisation

Ce document existe parce qu'un tableau de bord vert ne dit rien de la qualité
du produit. Il contient une expérience **négative** : ce qui a été tenté pour
améliorer le routage sur des requêtes jamais vues, ce que ça a donné, et ce qui
a été retiré du code en conséquence.

Protocole : `evals/heldout5.jsonl`, 31 requêtes écrites **avant** tout
diagnostic, mesurées **une seule fois**, après gel du code.

---

## L'expérience qui a échoué — et pourquoi elle a été retirée

Objectif : passer de 30,9 % @1 sur des requêtes jamais vues à autre chose.
Méthode : `evals/heldout5.jsonl`, **31 requêtes écrites avant tout diagnostic**,
mesurées une seule fois, à la fin.

### 1. Le diagnostic a écarté la piste évidente

Sur 94 requêtes inédites (jeux `heldout` à `heldout4`), le bon composant est
dans le top 50 pour **84 %** d'entre elles, mais en tête pour **31 %**. Ce n'est
donc pas un problème de vocabulaire mais de **classement** : le document est
trouvé, il finit 5ᵉ ou 27ᵉ.

Cause structurelle mesurée : `FIELD_WEIGHT` vaut **5,0 pour le nom et 1,8 pour
la description**, donc *un* mot dans le titre bat *deux* mots dans la
description (5,0 > 3,6). Exemple : `inherit-legacy-style` gagne sur
« I inherited a repo with zero tests and no docs » avec le seul mot `inherit`
(25,5), contre `codebase-onboarding` à 6,7.

### 2. La grille de pondérations ne produit que du bruit

17 variantes mesurées (poids de champs, arrêt, couverture pondérée par l'idf,
exigence de 2 termes). Sur 94 requêtes, **1 requête = 1,06 point** ; l'écart-type
binomial à p≈0,3 vaut 4,7 points. Aucune variante ne dépasse 1,1 σ, et **toutes
celles qui gagnent sur l'inédit perdent sur le dev** (`stop+fw_30+min2` :
+5,3 sur l'inédit, −6,0 sur le dev). C'est la signature d'un ajustement au jeu
de réglage, pas d'une amélioration.

### 3. Le thésaurus métier : +3,2 sur les jeux vus, **0,0 sur le jeu neuf**

60 entrées de vocabulaire logiciel (`cve`/`vulnerability`, `typo`/`lint`,
`credential`/`secret`, nominalisations). Résultat :

| jeu | @1 | @3 | plafond top-50 |
|---|---|---|---|
| dev (50) | 72,0 → 74,0 | 96,0 → 96,0 | — |
| heldout 1-4 (94, **vus pendant le diagnostic**) | 30,9 → 30,9 | 47,9 → 51,1 | 84,0 → 91,5 |
| **heldout5 (31, écrit avant)** | **12,9 → 12,9** | **35,5 → 35,5** | **84,0 → 84,0** |

Sur le seul jeu non contaminé, l'effet est exactement nul, plafond compris.
**Retiré du produit.** Le garder aurait ajouté 60 lignes de maintenance et une
impression d'amélioration sans preuve. Seul un correctif d'invariant a été
conservé : `ALIASES` contenait `test → testing → test`, un auto-alias.

### 4. Ce que ça dit du protocole lui-même

`heldout5` note **12,9 % @1** là où les quatre autres jeux inédits notent
27-37 %. Même plafond (84 %), même annotation (2,55 réponses acceptées par
requête en moyenne, comme les autres). La différence : les quatre premiers ont
été écrits par quelqu'un qui connaissait le catalogue ; le cinquième a été
écrit sans le regarder.

**Conséquence : les jeux inédits de 22-31 requêtes ne mesurent rien.** L'écart
entre auteurs est plus grand que l'effet de n'importe quel levier. Agrégé sur
les 125 requêtes jamais vues : **26,4 % @1, 44,8 % @3**.

### 5. Ce qui est verrouillé maintenant

`run-checks.sh` exécute `eccx eval --file evals/heldout5.jsonl --k 3
--min-recall 0.30`. La généralisation est une barre vérifiée, pas une intention.
`heldout5` est **brûlé** par cette ligne : il sert de garde anti-régression, plus
de jeu de test. Le prochain changement de classement exige un jeu neuf.

### 6. Ce qui reste à faire, et ce qui ne marchera pas

- **Pondérer mieux ne suffit pas.** 17 variantes, aucune au-delà du bruit.
- **Ajouter du vocabulaire ne suffit pas.** Mesuré à 0,0 sur le jeu neuf.
- **Ce qui reste** : un signal sémantique (plongements), ou une réduction du
  problème — promettre k=3 et optimiser @3, pas @1.
- **Avant tout nouveau réglage** : 300 requêtes inédites, pas 30. Tant que
  l'échantillon est à ±10 points, chaque « amélioration » est une croyance.

---

# La couche sémantique — ce qui a marché

Le diagnostic laissait une seule piste vivante : le **vocabulaire**. Un routeur
lexical ne relie pas « a dependency has a critical CVE » à `security-scan`,
parce qu'aucun mot n'est commun. Les plongements locaux le font.

## Ce qui a été construit

`eccxlib/semantic.py` + `router.score_hybrid`. `BAAI/bge-small-en-v1.5` en ONNX
via `fastembed` : **pas de torch, pas de service, pas de réseau à l'exécution**.

- Les 607 composants sont embarqués **une fois** (`eccx vectors`, 42 s) et le
  fichier de vecteurs porte une empreinte du catalogue : un index modifié
  invalide le cache au lieu de noter contre les mauvaises lignes.
- Une requête n'embarque qu'elle-même : **8 ms**, 823 ms de bout en bout en CLI
  contre 135 ms en lexical.
- `fastembed` est une dépendance **optionnelle**. Sans elle — ou hors ligne —
  le produit est exactement ce qu'il était, avec un message explicite.

## Effet mesuré

| jeu | n | @1 lexical → sémantique | @3 lexical → sémantique |
|---|---|---|---|
| `routing` (réglage) | 50 | 72,0 → 72,0 | 96,0 → **98,0** |
| `heldout` | 30 | 36,7 → **40,0** | 50,0 → **60,0** |
| `heldout2` | 30 | 26,7 → **30,0** | 46,7 → **56,7** |
| `heldout3` | 12 | 33,3 → 33,3 | 41,7 → **50,0** |
| `heldout4` | 22 | 27,3 → 27,3 | 45,5 → **50,0** |
| `heldout5` (scellé) | 31 | 12,9 → **19,4** | 35,5 → **41,9** |
| `heldout6` (scellé) | 40 | 17,5 → **20,0** | 25,0 → **30,0** |
| **agrégé, jamais vu** | **165** | **24,3 → 27,3** | **39,4 → 46,7** |

Six jeux sur six s'améliorent ou sont neutres. Sur les 94 requêtes de réglage,
McNemar exact : **7 gains, 0 perte en @3, p = 0,016** — ce n'est pas du bruit,
contrairement aux 17 variantes de pondération testées avant.

## Deux choses rejetées en route, avec les chiffres

**Le cross-encoder.** `ms-marco-MiniLM-L-6-v2` sur le top 20 : dev@1 **72 % →
48 %**. Un modèle entraîné sur des passages web ne sait pas ordonner des titres
de composants. En fusion douce il revient à l'égalité (33,0 / 56,4, identique à
l'hybride sans lui) pour +250 Mo et +120 ms par requête. **Retiré.**

**Le thésaurus métier** (60 entrées) : +3,2 pts @3 sur les jeux déjà vus,
**0,0 sur `heldout6`**, plafond compris. Retiré — détail dans la section
précédente.

## Où ça en est, honnêtement

**27,3 % @1 / 46,7 % @3 sur 165 requêtes jamais vues.** C'est deux fois mieux
qu'au début de cette phase sur @1, et toujours pas bon : une requête sur quatre
trouve le bon composant en tête.

Le plafond de récupération est à 84-87 % : le classement reste le goulot, pas
l'accès. Ce qui reste ouvert est donc **la discrimination entre candidats
proches** — un problème de rang, pas de vocabulaire, et les plongements y sont
moins bon qu'en rappel (+3 @1 contre +7,3 @3).

La prochaine étape honnête n'est pas un autre hyperparamètre : c'est un jeu de
300 requêtes (aujourd'hui, un écart de 3 points vaut 5 requêtes) puis un modèle
de rang, s'il en existe un qui généralise sur ce domaine. Aucun n'a été trouvé
dans ceux testés.

---

# Rendre le routage défendable — ce que la validation a détruit

Trois affirmations de la feuille de route ont été testées avant d'être
acceptées. **Deux étaient fausses.** Les corrections valent plus que les
résultats.

## A. La calibration par marge : retirée du produit

Première version : la marge relative entre le 1ᵉʳ et le 2ᵉ score. Mesurée sur
les 165 requêtes *regroupées*, elle semblait excellente — 24 % de couverture à
51 % @1. C'est la faute que je reproche à tout le monde depuis le début : le
seuil a été choisi sur les mêmes données qui l'ont validé.

Coupée par auteur :

| seuil 0,20 appliqué à | couverture | précision @1 |
|---|---|---|
| `heldout` 1-4 (là où le seuil a été réglé) | 27 % | **64 %** |
| `heldout` 5-6 (scellés) | 20 % | **29 %** |

La marge est *relative à la distribution de scores de la requête elle-même* :
sa signification dérive avec la difficulté. C'est une confiance sur le
classement, pas sur la justesse. **Retirée.**

## A′. Ce qui la remplace : le cosinus, seul signal qui transpose

Le cosinus du meilleur candidat est une quantité **absolue**. Testé dans les
deux sens :

| réglage | test | couverture | précision @1 |
|---|---|---|---|
| `heldout` 1-4 | `heldout` 5-6 | 7 % | 60 % (n=5, IC [20;100] — inutilisable) |
| `heldout` 5-6 | `heldout` 1-4 | 38 % | 50 % (IC [33;67], base 33 %) |

Direction cohérente, amplitude non établie. Comportement livré
(`CONFIDENT_COSINE = 0.63`), sur 165 requêtes :

| | couverture | @1 | @3 |
|---|---|---|---|
| CONFIANT | 31 % | **49 %** (IC95 **[35 ; 63]**) | 63 % |
| INCERTAIN | 69 % | 18 % | 41 % |

Le bas de l'intervalle (35 %) reste au-dessus de la référence (18 %) : la
séparation tient malgré 165 requêtes. La promesse publiée est délibérément
faible — *« environ 1,5× le taux de base, quand il se déclenche sur un tiers des
requêtes »*. Tout chiffre plus précis serait inventé.

## B. « 300 requêtes » : à moitié faux

| n | IC95 sur @1 |
|---|---|
| 40 | ±13,6 pts |
| 94 | ±8,9 pts |
| 165 | ±6,8 pts |
| 300 | ±5,0 pts |
| 600 | ±3,6 pts |

Pour une mesure **absolue**, 300 requêtes donnent ±5 pts. C'était le bon ordre
de grandeur. Mais détecter +5 pts entre deux systèmes non appariés demande
**~1 244 requêtes par bras** — hors de portée. Ce qui a réellement détecté le
gain sémantique, c'est un test **apparié** : 7 gains / 0 perte sur 94 requêtes,
p = 0,016.

**Conséquence : le protocole utile n'est pas « 300 requêtes » mais « comparaisons
appariées, pré-enregistrées, sur les mêmes requêtes ».** L'échantillon compte
beaucoup moins que le plan de comparaison.

## C. « Un modèle entraîné est la seule voie vers 60 % » : non démontré

Test direct : régression logistique à 9 features (score lexical normalisé,
cosinus, couverture, nombre de termes appariés, rangs lexical et sémantique,
type de composant, entraînée sur les composants candidats d'un lot de requêtes,
testée sur l'autre lot.

Premier résultat, enthousiasmant : **29,8 % @1 contre 20,0 %**. Puis l'erreur :

| sens | @1 appris | @1 fusion | apparié |
|---|---|---|---|
| 1-4 → 5-6 | 29,8 % | **24,6 %** | 4 gains / 1 perte, p = 0,375 |
| 5-6 → 1-4 | 41,8 % | 39,2 % | 7 gains / 5 pertes, p = 0,774 |

Les 20,0 % de référence étaient calculés sur **71** requêtes, les 29,8 % sur les
**57** que le modèle savait traiter. Sur les mêmes requêtes, le gain réel est
**+5,2 pts, non significatif**, et l'effet est **négatif en @3** dans l'autre
sens.

**Conclusion : avec 79 requêtes d'entraînement, un modèle appris ne bat pas la
fusion réglée à la main.** La prétention « seul un modèle entraîné peut
atteindre 60 % » reste une hypothèse non testée — elle demande des milliers de
paires annotées, pas 79.

## Où en est le produit, honnêtement

- Routage : **27,3 % @1 / 47,9 % @3** sur 165 requêtes jamais vues.
- Contrat de confiance : **49 % @1 [35;63] sur 31 % des requêtes**, 18 % le reste.
  C'est informatif, ce n'est pas une garantie.
- **Aucune voie vers 60 % n'est démontrée aujourd'hui.** Ni le réglage (±2 pts,
  bruit), ni le vocabulaire (0,0 hors échantillon), ni la taille du modèle
  (+5 pts @1, −2 pts @3), ni le rang appris (+5 pts @1, p = 0,375).

Ce que la session a réellement établi : *la difficulté n'est pas là où je la
cherchais.* Le plafond de récupération est à 84-87 %, donc le tri est le
problème — mais les quatre leviers testés pour l'attaquer n'ont rien donné de
significatif sur données jamais vues. Le prochain travail n'est pas de choisir
un levier, c'est de **rendre la mesure assez puissante pour départager des
effets de 5 points** : paires annotées à grande échelle, ou comparaisons
appariées nombreuses. Tant que ce n'est pas fait, tout gain annoncé est une
croyance.


---

# L'instrument qui donne une réponse : la courbe, pas le point

Neuf leviers de classement testés, aucun gain reproductible. Le problème n'était
pas le levier, c'était **le point de fonctionnement**. On optimisait @1 pour un
produit où l'agent relit une liste.

## Courbe mesurée, 165 requêtes jamais vues, hybride

| jeu | n | @1 | @3 | @5 | @10 | @20 | @50 |
|---|---|---|---|---|---|---|---|
| `heldout` | 30 | 40,0 | 60,0 | 60,0 | 66,7 | 83,3 | 93,3 |
| `heldout2` | 30 | 30,0 | 56,7 | 60,0 | 80,0 | 90,0 | 93,3 |
| `heldout3` | 12 | 33,3 | 50,0 | 66,7 | 66,7 | 75,0 | 75,0 |
| `heldout4` | 22 | 27,3 | 54,5 | 59,1 | 68,2 | 72,7 | 77,3 |
| `heldout5` | 31 | 19,4 | 41,9 | 45,2 | 58,1 | **71,0** | 83,9 |
| `heldout6` | 40 | 20,0 | 32,5 | 45,0 | 55,0 | **65,0** | 77,5 |
| **agrégé** | **165** | **27,3** | **47,9** | **53,9** | **64,8** | **75,8** | **84,2** |

## Le coût, mesuré

| k | tokens du shortlist | rappel agrégé |
|---|---|---|
| 3 | 104 | 47,9 % |
| 5 | 173 | 53,9 % |
| 10 | 344 | 64,8 % |
| **20** | **677** | **75,8 %** |
| catalogue entier | **1 071 212** | 100 % |

## Ce que ça change

**677 tokens pour avoir la bonne réponse dans la liste 3 fois sur 4** — contre
1 071 212 tokens pour lire le catalogue, ce qui est impossible. Ce n'est pas une
promesse diminuée, c'est le point de fonctionnement mesuré du produit : un
générateur de candidats pour un agent qui lit 20 descriptions et tranche.

Le routeur ne peut pas être un classifieur ici — neuf approches pour l'y forcer
ont échoué. Il peut être un générateur de shortlist, et il l'est à 75,8 %.

**C'est la seule affirmation de tout ce travail qui soit à la fois mesurée sur
données jamais vues, reproductible, et vérifiable par l'utilisateur en une
commande.** La barre est désormais dans le gate : `heldout5` à k=20 doit
rester au-dessus de 68 %.

## Ce que l'audit des échecs ajoute

Sur 24 échecs @1 examinés un par un, **5 étaient des réponses défendables** que
mon annotation refusait (`safety-guard` pour un force-push destructif,
`api-design` qui documente déjà les codes d'erreur, `large-file-decomposition`
pour du code illisible). L'éval sur-compte donc les échecs d'environ 20 % — dans
le sens pessimiste. Corrigé mentalement : le vrai @1 est plutôt 33 % que 27 %.
Ça ne change pas la conclusion, mais l'éval n'est pas non plus une mesure exacte.

## Bug trouvé en écrivant cette section

`eccx eval --k 20` **n'évaluait pas à 20** : `cmd_eval` appelait
`evaluate.run(...)` sans transmettre `k`, donc tout pool était de 5 et le
`recall@20` publié était calculé sur cinq candidats. Détecté parce que
`recall@20 == recall@5` sur un jeu où la courbe les sépare nettement. Corrigé, et
verrouillé par `TestEvalDepthReachesTheEvaluator`.

---

# La technologie qui a marché : la recherche au niveau des sections

Dix leviers avaient échoué. Le onzième n'était pas un réglage : **changer
l'unité de recherche**.

## Le diagnostic qu'on aurait dû faire plus tôt

Le catalogue décrit des **pratiques** (« Kubernetes deployment, autoscaling,
CrashLoopBackOff debugging »). L'utilisateur décrit un **symptôme** (« the pod
keeps restarting and the last state says it was killed for memory »). Aucun
terme commun avec la description de `kubernetes-patterns`. Mais plusieurs avec
**sa section CrashLoopBackOff**.

Une similarité calculée au niveau du document ne peut pas voir ça. Le signal
était là depuis le début : `index.json` contient déjà les sections H2
(`{"h": "When to Activate", "start": 5, "end": 15}`).

## Ce qui a été construit

**4 882 vecteurs de sections** pour 607 composants (9 min d'embedding, une
fois), plus la table section → document. Un composant est noté par **sa
meilleure section** (`numpy.maximum.at`), pas par la moyenne. Index 8,1 Mo.

## Le test qui tranche : 99 requêtes écrites avant toute mesure

Les 165 requêtes précédentes ne suffisaient pas (p = 0,18). La réponse n'était
pas de baisser la barre : **plus de requêtes jamais vues**. Deux fournées
écrites en aveugle, contre des composants qu'aucun jeu précédent n'utilisait
comme réponse attendue (449 des 607 n'avaient jamais servi), puis mesurées
**une fois chacune**, α et β gelés.

A/B via `evaluate.run`, même α, **seul le terme de section bascule** :

| | avant | après | apparié |
|---|---|---|---|
| @1 | 25/99 (25,3 %) | **33/99 (33,3 %)** | **10 gains / 2 pertes, p = 0,039** |
| @3 | 44/99 (44,4 %) | **52/99 (52,5 %)** | **9 gains / 1 perte, p = 0,022** |
| @20 | 73/99 (73,7 %) | 76/99 (76,8 %) | 6 / 3, p = 0,51 |

**C'est le premier résultat de ce projet qui soit réel, sur données jamais
vues, et significatif au seuil 0,05.** Il a coûté deux fournées, pas un
réglage.

## Ce qu'il faut dire contre son propre résultat

- **L'effet est un effet de tête de classement.** À @20 il disparaît
  (p = 0,51). Les sections remontent la bonne réponse au premier rang ; elles
  n'élargissent pas le filet.
- **33 % @1 reste 33 %.** C'est mieux que 25-27 %, très loin de 60 %. La
  promesse commerciale reste « shortlist à 77 % @20 pour 677 tokens », pas
  « routage juste du premier coup ».
- **99 requêtes, 10 gains.** Une première mesure donnait 6/0 p = 0,031 ; elle
  était fausse, la base comparée n'était pas la bonne (α = 1,5 au lieu de 3,0).
  Le chiffre retenu vient de l'A/B correct. Il a baissé de 0,031 à 0,039 —
  c'est le prix de l'exactitude.
- **Sur `heldout7` seul**, p = 0,0625 : non significatif. C'est le **pool de
  deux fournées indépendantes** qui donne la puissance. Pooler deux jeux
  écrits séparément, sans réglage entre les deux, est légitime ; pooler un jeu
  de réglage avec un jeu scellé ne l'est pas, et n'est pas fait ici.
- **@1 reste au niveau d'un humain qui connaît le catalogue**, pas au-dessus.

## Vue complète, même harnais, 224 requêtes

| jeu | n | @1 avant → après | @20 avant → après |
|---|---|---|---|
| heldout (réglage) | 30 | 36,7 → 50,0 | 80,0 → 90,0 |
| heldout2 (réglage) | 30 | 36,7 → 36,7 | 86,7 → 86,7 |
| heldout3 (réglage) | 12 | 41,7 → 41,7 | 75,0 → 83,3 |
| heldout4 (réglage) | 22 | 31,8 → 31,8 | 72,7 → 77,3 |
| heldout5 | 31 | 19,4 → 25,8 | 74,2 → 74,2 |
| heldout6 | 40 | 25,0 → 27,5 | 72,5 → 77,5 |
| heldout7 (aveugle) | 59 | 28,8 → 37,3 | 71,2 → 72,9 |
| heldout8 (aveugle) | 40 | 20,0 → 27,5 | 77,5 → 82,5 |
| **agrégé** | **224** | **29,9 → 35,3** | **75,4 → 79,0** |

Agrégé : @1 18 gains / 6 pertes p = 0,023 ; @3 19/7 p = 0,029 ; @20 14/6
p = 0,115.

## Un défaut trouvé en écrivant cette section

`eccx eval` chargait `semantic.load_vectors()` — les vecteurs de **documents**
seulement — alors que `eccx recall` notait par section. L'évaluateur mesurait
donc **un modèle que le produit ne livrait pas** : 28,8 % au lieu de 37,3 % sur
`heldout7`. C'est la même famille que le bug `--k` : le harnais et le produit
divergent, et le chiffre reste crédible.

Corrigé (`load_all`), et verrouillé par un test qui assert le **classement**,
pas l'appel : une première version espionnait `load_all` et **survivait à la
mutation**, parce que `load_vectors` délègue à `load_all` et que l'espion
sonnait quand même. Le test actuel échoue si on remet l'ancien code.

## Autres technologies testées dans cette passe

| approche | résultat |
|---|---|
| préfixe d'instruction BGE sur la requête | +1,0 @1 sur le réglage, **0,0 sur le scellé** |
| `snowflake-arctic-embed-xs` | **pire** (scellé 14,1 @1 contre 19,7) |
| `nomic-embed-text-v1.5` | **OOM** (1,9 Go de RAM disponibles) |
| `jina-v2-small` | **disque plein** (/tmp 992 Mo) |
| `bge-base` (×2) | +5 @1, **−2 @3** |
| α seul 1,5 → 3,0 | toutes les profondeurs montent |
| **α = 3,0 + sections β = 5,0** | **retenu** |

## Où en est le produit

Gate : `heldout5` @3 ≥ 38 %, @20 ≥ 70 % ; `heldout7` @1 ≥ 33 %, @20 ≥ 70 % ;
`heldout8` @1 ≥ 22 %. Reproductible par n'importe qui :

    ./eccx eval --file evals/heldout7.jsonl --k 20 --no-sections --json   # avant
    ./eccx eval --file evals/heldout7.jsonl --k 20 --json                 # après

---

# Reranker cross-encoder : testé, éliminé

Proposition naturelle après un gain en tête de classement : garder le pool de
20 et le **réordonner** avec un cross-encoder local. Mesuré, pas supposé.

`Xenova/ms-marco-MiniLM-L-6-v2`, 50 requêtes aveugles (`heldout9`, écrites
avant la mesure), réordonnancement du top-20 du système livré :

| | avant | après | apparié |
|---|---|---|---|
| @1 | 38,0 % | **2,0 %** | **5 gains / 51 pertes**, p < 0,0001 |
| @3 | 58,0 % | 10,7 % | 6 / 71, p < 0,0001 |
| @20 | 88,0 % | 88,0 % | identique par construction |

Contrôle de direction passé (le modèle note bien le passage pertinent au-dessus
du non-pertinent), alignement section→texte vérifié (`4 882` lignes, `span`
identique au bit près). **L'instrument n'est pas en cause, le modèle l'est.**

## Pourquoi, et ce que ça enseigne

Le modèle est entraîné sur MS MARCO : *la requête et le passage parlent-ils de
la même chose, littéralement*. Toutes les paires reçoivent des scores très bas
et très proches (≈ −11), signe qu'il ne reconnaît rien ; l'ordre qui en sort est
du bruit, et il est **systématiquement inverse** de notre fusion (2 % < 5 % du
hasard).

C'est cohérent avec tout le reste : BM25 intégral donnait @1 nul, le thésaurus
0,0, les préfixes 0,0. Le signal utile ici n'est **pas** de la pertinence
lexicale — c'est l'abstraction symptôme → pratique. Un modèle de pertinence
générique ramène au littéral, donc détruit le seul signal qui marche.

Conséquence pour la suite : arrêter d'empiler des modèles de pertinence. Le
gisement restant (@1 35 % pour un plafond @20 de 80 %) n'est pas là.
