# Ce que je propose — avis de dev senior

Écrit après la mesure, pas avant. Tous les chiffres de ce document sortent du
même harnais, et les scripts pour les reproduire sont dans le dépôt.

---

## 1. Où en est réellement le travail

**Ce qui marche, mesuré sur 149 requêtes aveugles** (`heldout7/8/9`, écrites
avant mesure, aucun paramètre réglé dessus) :

| | avant (doc seul) | après (sections) | apparié |
|---|---|---|---|
| @1 | 28,2 % | **34,9 %** | 13 gains / 3 pertes, **p = 0,021** |
| @3 | 47,7 % | **54,4 %** | 12 / 2, **p = 0,013** |
| @20 | 77,2 % | 80,5 % | 9 / 4, p = 0,27 |

Le produit livre une **shortlist à 80,5 % @20 pour 677 tokens**, contre
1 071 212 tokens pour le catalogue entier. C'est un rapport de **1 582×**.

**Le détail qui compte** : sur `routing.jsonl`, le jeu contre lequel tout a été
développé, les sections font **perdre** 2 points (70,0 → 68,0). Le gain
n'apparaît que sur ce qui n'a jamais été vu. C'est la signature d'un vrai gain
et non d'un réglage — mais ça dit aussi que l'ancien routeur était déjà
sur-ajusté à ce jeu.

**Ce qui ne marche pas, et que j'ai arrêté de payer** : le reranker
cross-encoder, mesuré aujourd'hui sur 50 requêtes aveugles. **5 gains,
51 pertes, p < 0,0001.** Contrôle de direction passé, alignement vérifié. Le
modèle n'est pas cassé : il ramène au littéral, et le seul signal qui marche ici
est l'abstraction symptôme → pratique. Comme BM25 (0,0), le thésaurus (0,0), les
préfixes (0,0), `heads` (0,0).

**Ce qui manquait pour livrer, réparé aujourd'hui** : pas de `LICENSE` (MIT
posée), `pyproject.toml` sans `[project]` (ajouté : `pip install -e .` installe
la commande `eccx`, qui tourne depuis n'importe quel répertoire — vérifié).

**Le vrai problème, que personne ne regarde** : l'instrument est accroché à un
catalogue qui ne m'appartient pas. `affaan-m/ECC` peut renommer 300 skills
demain ; mon index, mes 149 requêtes et mes chiffres ne valent plus rien. Je suis
en train de raffiner un livrable dont la valeur tient à un dépôt tiers, sans
propriétaire, sans roadmap, sans obligation.

---

## 2. Ce que je refuse de faire

- **MCP, dashboard, packaging « produit »** avant d'avoir un utilisateur réel.
  Ça ne change aucun chiffre et ça donne l'illusion d'avancer.
- **Continuer à empêcher des modèles de pertinence.** Trois essais, trois
  échecs, avec la même explication. Ce n'est plus une hypothèse, c'est une
  impasse.
- **Vendre 60 % @1.** Je ne sais pas le faire avec ce que je connais, et une
  shortlist honnête vaut mieux qu'un chiffre gonflé qui s'écroule au premier
  client.
- **Annoncer un gain sans test apparié.** C'est ce qui a produit le 0,031 faux
  de la session dernière ; il a fallu le corriger en 0,039 le lendemain.

---

## 3. Trois options, et ce que chacune achète

### Option A — Livrer l'instrument tel quel, avec sa promesse honnête
**Ce que c'est** : `eccx` route un symptôme vers 20 composants du catalogue ECC
pour 677 tokens. Il ne prétend pas trouver le bon du premier coup (34,9 %), il
prétend que le bon y est 4 fois sur 5.
**Pour qui** : ceux qui installent ECC et se noient dans 607 skills, 55 agents
et 56 commandes. ECC a ~285 000 étoiles et sa skill la plus installée est à
**18 189 installs** : le besoin est réel, la distribution existe.
**Ce que ça vaut** : une démo courte à montrer, pas un produit. **2 jours.**
**Risque** : dépendance à un dépôt tiers, aucune barrière à l'entrée.

### Option B — Changer de catalogue : le mien
**L'idée** : ce routeur n'a de valeur que si le corpus est **volumineux,
personnel et non indexable par `grep`**. Le catalogue ECC est un bon banc
d'essai ; mon propre corpus (notes, décisions, repos internes, comptes rendus)
est un vrai besoin, et lui ne changera pas sous mes pieds.
**Ce qui est déjà construit et transférable** : indexation des sections, fusion
hybride, budget de tokens dur, la machinerie d'évaluation (jeux aveugles, tests
appariés, IC), les règles anti-surapprentissage. Tout sauf le corpus.
**Ce que ça coûte** : **une semaine**, dont un jour pour réunir le corpus et
écrire 60 requêtes réelles tirées de mes propres sessions passées.
**Pourquoi je le préfère** : c'est la seule des trois options où le chiffre
final mesure quelque chose que j'utiliserai vraiment.

### Option C — Arrêter
**Critère de sortie explicite**, que j'accepte : si, sur mes 60 requêtes
réelles, le routeur ne bat pas « `grep` + le README » de **+5 points @3**, alors
il ne rend pas service et je publie la note de mesure (une douzaine de pistes
documentées, une retenue) et je m'arrête là.
**Je ne le propose pas aujourd'hui** parce que le gain est réel, significatif et
reproductible. Mais je refuse de le poursuivre sans ce critère d'arrêt.

---

## 4. Ma recommandation

**A pendant 2 jours, puis B pendant 5, avec le critère d'arrêt de C.**

Concrètement :

| jour | quoi | critère d'acceptation |
|---|---|---|
| 1 | durcir la livraison | `pip install` propre sur un environnement vierge, `eccx doctor` vert, quickstart en 3 commandes, latence froide/chaude publiée |
| 2 | banc reproductible | `tools/bench.sh` régénère les 9 jeux et la courbe en < 5 min chez un tiers |
| 3 | corpus personnel | mes notes + 3 dépôts indexés, même machinerie |
| 4 | 60 requêtes réelles | tirées de mes sessions passées, écrites avant mesure |
| 5 | décision | +5 pts @3, sinon arrêt et publication de la note |

**Ce que je livrerais à un acheteur dans l'option A**, sans mentir : une
shortlist à 80 % pour 677 tokens, un `--budget` qui est une promesse dure, un
gate à 491 tests et 90 % de couverture, 9 jeux aveugles et leurs tests appariés,
et un document qui liste les échecs. Il y a déjà plus de rigueur ici que dans la
plupart des outils de ce genre — mais la rigueur n'est pas la demande : la
demande, c'est « trouve-moi le bon ».

---

## 5. Ce que je ne signerai pas

- **« Le routage est réglé »** : 34,9 % @1 n'est pas réglé. Le bon résultat est
  dans la shortlist 8 fois sur 10, ce n'est pas la même promesse.
- **Les 285 000 étoiles comme preuve de marché** : 18 189 installs pour la skill
  la plus téléchargée, ~6 % du nombre d'étoiles. Les étoiles mesurent
  l'attention, pas l'usage.
- **Les 84-87 % comme plafond définitif** : c'est le plafond *de ce catalogue
  avec ces 607 descriptions*. Un corpus mieux écrit le relèverait ; un corpus
  mal écrit l'abaisserait. C'est une propriété du corpus, pas de l'instrument.

---

## 6. La question qui décide de tout

**Quel corpus voulez-vous réellement router ?**

- s'il y a un catalogue tiers à interroger (ECC, un dépôt client, une doc
  interne volumineuse) → option A, et je livre dans deux jours ;
- si c'est votre propre matière → option B, et le chiffre qui compte sera mesuré
  sur vos requêtes, pas sur les miennes.

Tant que cette question n'est pas tranchée, je ne construis plus rien : je
serais en train d'optimiser un banc d'essai.

---

## 7. Avantages et inconvénients, option par option

### A — Livrer sur un catalogue qui existe (ECC, doc interne, dépôt client)

**Avantages**
- **Rien à construire** : 607 composants indexés, 9 jeux aveugles, 149 requêtes,
  tests appariés. Le travail de mesure est déjà payé.
- **2 jours** et c'est montrable, avec des chiffres défendables.
- **Distribution toute trouvée** si c'est ECC : 285 000 étoiles, la skill la plus
  installée à 18 189 téléchargements, licence MIT.
- **Le corpus est écrit par quelqu'un d'autre** : je n'ai pas à produire de
  contenu pour que l'outil serve.

**Inconvénients**
- **La valeur tient à un dépôt que je ne contrôle pas.** Un renommage de 300
  skills et mon index, mes jeux, mes chiffres tombent ensemble.
- **Concurrence native possible** : ECC v2 pousse un *control plane* et un
  dashboard (source tierce, à vérifier). Le jour où ils livrent leur propre
  découverte, l'outil devient redondant.
- **Aucune barrière à l'entrée** : n'importe qui branche un routeur sur le même
  catalogue.
- **L'usage réel après la démo est souvent nul** : on installe, on regarde une
  fois, on revient à `Ctrl-F`.
- **Le corpus est déjà « routable »** : les descriptions de skills sont écrites
  pour être trouvées. Je gagne sur un terrain préparé par d'autres.

### B — Le porter sur votre propre matière

**Avantages**
- **Besoin réel et quotidien** : seule option où le chiffre final mesure
  quelque chose que vous utiliserez demain.
- **Le fossé, c'est vos données.** Personne d'autre n'a vos notes, vos décisions,
  vos comptes rendus. Seule version défendable commercialement.
- **Le corpus ne bouge plus sous vos pieds** : vous le possédez, vous le
  re-indexez, vos jeux de test restent valides.
- **Vous mesurez le bon critère** : non plus « le bon composant est-il au rang
  1 », mais « ai-je trouvé plus vite qu'avec `grep` ».

**Inconvénients**
- **Il faut un corpus structuré.** Le gain vient des sections : 500 notes de
  trois lignes n'ont rien à découper et le mécanisme s'effondre. Matière non
  titrée = un jour de mise en ordre d'abord.
- **Démarrage à froid** : sans requêtes passées tracées, vous écrirez les
  requêtes de test après avoir vu les résultats — le gain redevient un mirage.
  C'est le piège qui a coûté cette session entière.
- **Une semaine**, et la valeur est **privée** : elle ne se met pas en avant
  comme une démo sur un dépôt à 285 000 étoiles.
- **Si le corpus fait moins de ~200 documents, `grep` gagne.** C'est un outil
  pour gros corpus, pas une amélioration universelle.

### C — Démo maintenant, portage ensuite (ma recommandation)

**Avantages**
- **Ne perd rien des deux précédentes** : les deux jours de durcissement
  (licence, `pip install`, banc reproductible, latence) servent dans les deux
  scénarios.
- Le démonstrateur **valide l'instrument** de façon publique et bon marché.
- **Sortie à bas coût** : si le portage échoue au critère d'arrêt, il reste une
  démonstration solide et une note de mesure.

**Inconvénients**
- **Risque classique : on ne fait jamais la seconde moitié.** La démo est
  agréable, le portage est du travail. C'est le piège « on industrialisera
  plus tard ».
- **Le risque de churn du catalogue ne disparaît pas**, il est repoussé de
  cinq jours.
- **Retarde la seule réponse qui compte** : est-ce que ça résout *votre*
  problème ?

### D — Arrêter et publier la note

**Avantages**
- **Coût quasi nul** : un jour de rédaction.
- **Matière différenciante** : une douzaine de pistes documentées, une retenue,
  des tests appariés et des échecs nommés. Dans un domaine saturé d'annonces,
  c'est ce qui se lit.
- **Arrête le paiement** : plus de banc d'essai à entretenir.

**Inconvénients**
- **On jette quelque chose qui marche** : p = 0,021 sur 149 requêtes aveugles.
  Modeste, mais réel.
- **Aucun actif utilisable au quotidien** : un document ne route pas vos notes.
- **La note peut ne pas être lue** si elle est mal faite — et bien la faire,
  c'est encore du travail.

---

## 8. La règle de décision, en deux questions

| si… | …alors |
|---|---|
| **plus de 200 documents titrés** ET **des requêtes passées tracées** | **B**, sans détour. Le mécanisme des sections est fait pour ça. |
| le corpus existe mais **aucune requête passée tracée** | **C**, et le jour 4 sert à reconstituer 60 requêtes réelles depuis vos sessions avant de mesurer quoi que ce soit. |
| **ni l'un ni l'autre**, mais un catalogue tiers qui vous agace | **A**, deux jours, et c'est fini. |
| **moins de 100 documents** | **D**. `grep` fait déjà le travail — je préfère vous le dire que vous vendre un routeur. |

**Ma recommandation reste C** : les deux jours de durcissement sont dus de toute
façon, et le critère d'arrêt (+5 points @3 sur vos propres requêtes, sinon on
s'arrête et on publie) empêche les deux pièges symétriques — construire pour
rien, ou jeter un résultat qui valait mieux.
