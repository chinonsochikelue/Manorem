<p align="center">
  <picture>
    <source
      media="(prefers-color-scheme: dark)"
      srcset="assets/manorem_logo_dark.svg"
    />
    <source
      media="(prefers-color-scheme: light)"
      srcset="assets/manorem_logo.svg"
    />
    <img
      src="assets/manorem_logo_dark.svg"
      alt="Manorem"
      width="250"
      height="216"
    />
  </picture>
</p>

# Manorem

**Français** · [English](README.md) · [Igbo](README.ig.md) · [Español](README.es.md) · [简体中文](README.zh-CN.md)

Transformer une idée en vidéo explicative narrée — sans laisser un modèle de langage
écrire le code d'animation.

Le postulat du pipeline : un LLM est bon pour décider *ce qu'une scène doit
signifier* et mauvais pour décider *où placer les choses*. Le modèle n'émet donc
jamais de code Manim, ne choisit jamais une coordonnée et ne nomme jamais un numéro
d'image. Il émet du **Visual IR** : un document fortement typé, validé et versionné
qui décrit des objets, des relations, une narration et une intention datée. Un
compilateur déterministe en dérive la mise en page, les keyframes de caméra et les
instructions de rendu.

Un IR invalide n'atteint jamais le renderer. Cette seule règle justifie l'essentiel
de ce dépôt.

## État

Les Milestones 1 à 3 sont terminés : les huit paquets prévus par la configuration
du workspace sont implémentés, `manorem build` mène d'une idée à une vidéo
sous-titrée hors ligne et peut produire un audio narré via son chemin TTS
déterministe stub/cassette, Visual QA (`VQA6xx`) évalue un rendu terminé à la
recherche de défauts géométriques et les renvoie vers la réparation de l'IR, et
la parole synthétisée — lorsqu'elle est activée — devient l'autorité de timing sur
laquelle toute la vidéo est montée. Ce qui existe est complet, strictement typé et
testé (plus de 1 000 tests, `mypy --strict` sans erreur) ; rien n'est esquissé en
faisant croire qu'il est plus abouti qu'il ne l'est.

| Paquet | État | Contenu |
| --- | --- | --- |
| `manorem-core` | implémenté | settings, logging structuré, le vocabulaire de diagnostics, stockage d'objets, hachage canonique |
| `manorem-ir` | implémenté | le Visual IR : modèles, export JSON Schema, validation à trois niveaux, résolution symbolique du temps |
| `manorem-skills` | implémenté | paquets de vocabulaire métier (types d'objets, opérations, contraintes supplémentaires) |
| `manorem-compiler` | implémenté | IR → `RenderPlan` : normalisation, résolution de layout, timing, caméra, autofix |
| `manorem-renderer` | implémenté | worker Manim isolé (et un stub) produisant une vidéo par scène, plus le Visual QA géométrique |
| `manorem-compositor` | implémenté | concaténation des scènes, transitions, timeline audio, multiplexage A/V, sous-titres SRT/VTT |
| `manorem-ai` | implémenté | fournisseurs LLM (Gemini / Anthropic / OpenAI / bascule de pool de clés / cassettes enregistrées / stub) et fournisseurs TTS (stub / cassette / parole compatible OpenAI), agents de planification, réparation bornée |
| `manorem-cli` | implémenté | le point d'entrée `manorem` : `build`, `validate`, `compile`, `render`, `vqa`, `schema` |

Honnête sur les limites : Visual QA mesure des défauts **géométriques** — texte hors
de la scène, objets qui se chevauchent, texte illisible tant il est petit, mauvais
contraste sur le fond déclaré — pas la qualité artistique ; il n'y a délibérément
aucun « score de qualité visuelle » global, et un rapport propre signifie *aucun
défaut mesuré*, pas *bonne vidéo*. Sauf si on lui demande d'évaluer
(`manorem build --vqa`), un rendu rapporte encore `quality=None` plutôt que « c'est
réussi ». La validation de provenance prouve qu'une URL citée a réellement été
récupérée, **non** que la source étaie l'affirmation. La narration peut être
synthétisée ou laissée muette : avec `--audio`, un fournisseur de synthèse vocale
donne voix à chaque segment et sa durée *mesurée* pilote les fenêtres de narration,
l'ancrage des cues et les sous-titres — l'audio fait autorité sur le timing. Sans
audio — le comportement par défaut, `--no-audio`, ou lorsque la synthèse est
indisponible —, le timing de la narration retombe sur l'estimation en mots par
minute, si bien que la vidéo reste muette mais rythmée, avec des sous-titres
synchronisés. Un échec de synthèse retombe scène par scène et est observable via les
diagnostics `AUD9xx`. `examples/scratch/scene.py` est un fichier Manim écrit à la
main, conservé pour référence et hors pipeline.

## La forme de l'ensemble

```
idea ──► story plan ──► visual plan ──► Visual IR
                                           │
                                           ▼
                                       validate ◄────────┐
                                           │             │
                                           ▼             │
                                 synthesize narration    │
                                           │             │
                                           ▼             │
                                   measured timing       │
                                           │             │
                                           ▼             │
                                       compile ──────────┤  repair
                                           │             │  (bounded,
                                           ▼             │   diagnostic-
                                        render           │   driven)
                                           │             │
                                           ▼             │
                                         VQA ────────────┘
                                           │
                                           ▼
                                 composite A/V + subs
                                           │
                                           ▼
                                         video
```

La narration est synthétisée *avant* la compilation : ses durées par segment
mesurées réécrivent les fenêtres de narration, de sorte que le compilateur quantifie
un timing réel plutôt qu'une estimation. Quand l'audio est désactivé, cette étape est
sautée et les fenêtres restent sur l'estimation en mots par minute — le même chemin,
une bifurcation plus tôt.

Deux propriétés tiennent la conception.

**L'IR est la source de vérité.** Il est sémantique : un cue `flow` signifie
« montrer des données qui vont de A à B », pas `MoveAlongPath`. Les positions sont
une *intention* (`auto`, un slot nommé, un ancrage sur un autre objet), pas des
coordonnées. Le temps est *symbolique* (« quand la narration sur les satellites
commence »), pas des secondes. Tout ce qui est mécanique est dérivé en aval, et c'est
pourquoi le même IR peut être reciblé en 16:9, 9:16 et 1:1 en changeant un seul champ.

**Les échecs sont structurés, pas textuels.** Chaque sous-système émet le même type
`Diagnostic`, adressé par un JSON Pointer RFC 6901, avec un code namespacé. C'est ce
qui rend la boucle de réparation possible : elle consomme des codes et des pointeurs,
pas de la prose, et elle est bornée — jamais une reprise sans fin.

## Arborescence

```
packages/
  core/src/manorem_core/         settings, logging, diagnostics, errors, ids, hashing, storage
  ir/src/manorem_ir/             project, scene, objects, props, layout, camera, narration,
                                 timeline, timing, resolve, geometry, format, enums,
                                 operations, validate, schema
  skills/src/manorem_skills/     skill protocol + registry; core, networks, geography, dataviz packs
  compiler/src/manorem_compiler/ passes P0–P8, layout solvers, scheduler, autofix, RenderPlan
  renderer/src/manorem_renderer/ Renderer protocol, Manim plan interpreter, stub renderer, sandbox
  compositor/src/manorem_compositor/ FFmpeg argv builder, scene concat, audio timeline, subtitles
  ai/src/manorem_ai/             LLMProvider, Gemini/cassette/stub, agents, prompts, pipeline, repair
  cli/src/manorem_cli/           the `manorem` command line
tests/
  support/                       builders d'IR/IA et assertions de diagnostics partagés par la suite
  unit/                          par paquet : core, ir, skills, compiler, renderer, compositor, ai, cli
  integration/                   l'exemple GPS écrit à la main, de bout en bout
examples/gps/                    le Visual IR de référence : neuf scènes, plus une fixture à référence cassée
examples/scratch/                fichier Manim de référence brut, exclu du lint
```

Il n'existe volontairement aucune distribution racine : chaque unité de code vit dans
`packages/*` afin que le worker de rendu isolé puisse installer le moteur sans
entraîner de dépendances d'API ou de service. Les imports relatifs franchissant les
frontières de paquet sont interdits par le lint : le graphe de dépendances reste
acyclique et lisible — `manorem_core` ne sait rien de Manim, des fournisseurs de LLM
ni de l'IR.

## Le Visual IR

Un `Project` contient des `Episode`s, qui contiennent des `Scene`s. La scène est
l'unité d'écriture, de génération, de rendu, de cache et de réparation : elle est
autonome et ne référence rien d'extérieur, ce qui rend viable la génération par IA
scène par scène (les limites d'imbrication de la sortie structurée excluent de
générer le projet entier) et la réparation locale — un patch qui corrige la scène 4
ne peut pas perturber la scène 7.

Dans une scène :

- **objects** — un ensemble fermé de types sémantiques (`text`, `math`, `chart`,
  `globe`, `network`, …), chacun avec son modèle de props typé : « un chart sans
  series » est donc une erreur de schéma, pas un crash du renderer
- **placement** — `auto` (le moteur de layout décide), `slot`, `anchor` (relatif à un
  autre objet), ou des coordonnées `stage` explicites en dernier recours
- **layout** — une intention déclarée (`grid`, `radial`, `tree`, `split`, …), résolue
  plus tard
- **relationships** — des arêtes typées qui alimentent les solveurs de layout, les
  contraintes des skills et parfois la géométrie (`points_to` devient une flèche)
- **narration** — des segments avec des rôles (`hook`, `revelation`, `payoff`, …) ;
  les temps sont dérivés, jamais écrits à la main
- **timeline** — des `Cue` : une opération sémantique, ses cibles, son début, sa
  durée, et *pourquoi* elle existe
- **camera** — une pose initiale et des limites ; les *mouvements* de caméra sont des
  cues ordinaires, donc ordonnables et datables par rapport aux visuels

Les positions vivent dans le **stage space** : `[-1, 1]` sur les deux axes, où le
carré unité est la zone sûre visible dans tous les formats. Aucune coordonnée monde
et aucune constante 16:9 n'apparaît en amont de la passe du compilateur qui projette
le stage space vers les unités Manim.

### Écrire une scène

```python
from manorem_ir import (
    Cue, DotProps, Episode, NarrationSegment, ObjectKind, Project, Scene,
    SceneObject, SemanticOp, TextProps, at_narration, lasting, validate_project,
)

scene = Scene(
    id="intro",
    name="Where am I?",
    intent="Open with the question the video answers.",
    objects=[
        SceneObject(id="title", kind=ObjectKind.TEXT,
                    props=TextProps(content="Where am I?", role="title")),
        SceneObject(id="phone", kind=ObjectKind.DOT, props=DotProps()),
    ],
    narration=[
        NarrationSegment(id="hook", text="Where are you right now?"),
        NarrationSegment(id="answer", text="Your phone knows.", mentions=["phone"]),
    ],
    timeline=[
        Cue(id="show_title", op=SemanticOp.SHOW, targets=["title"],
            at=at_narration("hook"), duration=lasting(1.0)),
        Cue(id="show_phone", op=SemanticOp.SHOW, targets=["phone"],
            at=at_narration("answer"), duration=lasting(1.0)),
        Cue(id="pulse", op=SemanticOp.HIGHLIGHT, targets=["phone"],
            at=at_narration("answer", "end"), duration=lasting(0.8)),
    ],
)

project = Project(id="gps", title="How GPS knows where you are",
                  episodes=[Episode(id="main", title="Main", scenes=[scene])])

assert not validate_project(project).has_errors
project.content_hash()          # '5446673f6e6d...' — un IR identique donne le même hash
```

Rien ici ne dit où se place le titre, quand 1,4 seconde s'est écoulée, ni quelle
classe Manim dessine un point. Tous les modèles sont figés (`frozen`) : une passe du
compilateur produit un nouveau document au lieu de muter celui qu'on lui a donné.

### En transit

Les modèles *sont* le schéma. `manorem_ir.schema` exporte le JSON Schema de
`Project` et `Scene`, en calcule l'empreinte pour détecter les dérives, et sert de
source aux types TypeScript de l'IR ainsi qu'à la requête de sortie structurée
envoyée au modèle. Deux systèmes de types maintenus à la main divergent ; l'un
généré depuis l'autre ne peut pas.

```json
{
  "id": "pulse",
  "op": "highlight",
  "targets": ["phone"],
  "params": {},
  "at": { "at": "narration", "segment": "answer", "edge": "end", "offset": 0.0 },
  "duration": { "kind": "seconds", "seconds": 0.8 },
  "easing": null,
  "why": null
}
```

Les paramètres d'un cue sont limités à des scalaires JSON plats — une frontière de
sécurité structurelle, non procédurale. Un paramètre ne peut être ni une structure
imbriquée ni une expression : rien ne peut faire passer du comportement en douce
vers le renderer. Une skill qui a besoin d'une configuration plus riche déclare
plutôt un nouveau type d'objet.

## Validation

Trois niveaux, chacun signalant là où un défaut est réellement détectable :

- **T1 structurel** — la forme du document. Pydantic couvre les types, les bornes et
  les discriminants ; ce niveau ajoute ce qu'un schéma ne peut pas exprimer : ids en
  double, scènes vides, durées qui se quantifient à zéro image à la cadence cible (le
  même IR est correct à 60fps et dégénéré à 15fps).
- **T2 référentiel / sémantique** — le document *veut-il dire* quelque chose. Chaque
  référence se résout, chaque signature d'opération est satisfaite, la timeline est
  acyclique, rien n'est utilisé avant d'être affiché.
- **T3 rythme et géométrie** — bien formé mais douteux : temps morts, scène
  surchargée, objets qui se chevauchent ou sortent du cadre, narration qui déborde de
  sa scène. Avertissements par défaut, promouvables en erreurs par politique.

Les trois sont calculés depuis l'IR et le plan résolu, jamais depuis des pixels. Ils
établissent qu'un plan est *bien formé*, ce qui n'est pas la même affirmation que
*c'est réussi* — savoir si l'image finie se lit vraiment se mesure après le rendu, à
l'étape Visual QA et via ses codes `VQA6xx`.

Un constat nomme un code, une sévérité et un pointeur dans le document fautif. Pour
la scène ci-dessus dont le cue `pulse` viserait par erreur `"phones"` :

```python
>>> for d in validate_scene(broken):
...     print(d)
error: IR201_UNKNOWN_OBJECT_REF [intro] at /timeline/2/targets/0: cue 'pulse' targets unknown object 'phones'
```

Les codes sont namespacés par l'étape qui les lève :

| Plage | Étape |
| --- | --- |
| `IR1xx` | structurel |
| `IR2xx` | référentiel / sémantique |
| `IR3xx` | lints de rythme et de géométrie |
| `CMP4xx` | compilation |
| `RND5xx` | rendu |
| `VQA6xx` | qualité visuelle |
| `MUX7xx` | composition |
| `RES8xx` | provenance de recherche |
| `AUD9xx` | audio de narration / timing |

Tout code `IR2xx` figure dans `SEMANTIC_ERROR_CODES`, et l'autofix déterministe n'a
pas le droit d'y toucher — il escalade vers l'agent de réparation borné. « Corriger »
silencieusement une référence pendante jette l'intention de l'auteur et cache un vrai
défaut du planificateur derrière un rendu d'apparence plausible.
`Diagnostic.autofixable` est dérivé de cet ensemble au lieu d'être stocké : celui qui
construit un diagnostic ne peut donc pas requalifier une erreur sémantique en anodine.

La résolution du temps vit dans `manorem_ir.resolve` plutôt que dans le compilateur
parce que deux consommateurs en ont besoin et ne doivent pas diverger : les
validateurs T2/T3 et la passe du compilateur qui quantifie les mêmes nombres en
images. La résolution itère jusqu'à un point fixe au lieu de trier topologiquement :
une timeline partiellement cassée fournit encore des temps utiles pour les cues bien
formés — ce qui garde des diagnostics précis au lieu de tout réduire à un seul
« la timeline est cassée ».

### Autorité de timing de l'audio

Quand l'audio est activé, chaque segment de narration est synthétisé indépendamment.
La durée mesurée de chaque clip est injectée dans les champs existants
`NarrationSegment.start/end` avant la compilation. Les segments sont disposés bout à
bout au sein de leur scène, y compris le `pause_after` de chaque segment.

Le système de timing symbolique existant résout alors `at_narration(...)` par rapport
à ces fenêtres mesurées. Le compilateur n'a donc besoin d'aucune logique de timing
spécifique à l'audio : le timing réel de la narration emprunte le même chemin de
résolution que celui utilisé par les estimations en mots par minute. Le compositor
rattache ensuite les assets audio correspondants aux `AudioCue`s compilés et effectue
l'assemblage A/V final.

Il n'existe aucune seconde timeline audio ni aucune seconde horloge de sous-titres.

## Démarrage

Nécessite Python ≥ 3.13 (le dépôt épingle 3.14) et [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-packages
```

```bash
make test
```

La configuration passe par l'environnement avec le préfixe `MANOREM_` ; copiez
`.env.example` vers `.env` et modifiez-le. Les valeurs par défaut sont choisies pour
fonctionner hors ligne : le fournisseur LLM vaut `cassette` (rejoue des réponses
enregistrées, sans clé d'API), la qualité de rendu `draft`, et la boucle de réparation
au plus 2 tentatives.

## Utiliser la CLI

`manorem`, ce sont six verbes sur un même pipeline. `validate` et `compile` opèrent
sur un projet Visual IR, `render` et `vqa` sur un `RenderPlan` compilé, `schema`
exporte le JSON Schema, et `build` exécute tout le pipeline de l'idée à la vidéo, le
fonctionnement hors ligne étant disponible comme un mode strict sans réseau.

```bash
manorem validate examples/gps/ir.json
manorem compile examples/gps/ir.json --aspect 16:9 -o plan.json
manorem render plan.json --quality draft -o gps.mp4
manorem vqa plan.json
manorem build "How GPS determines your location." --aspect 16:9 --vqa -o out/
manorem build "How GPS determines your location." --audio --tts stub --offline -o out/
manorem build "How GPS determines your location." --no-audio --offline -o out/
```

`build` écrit chaque artefact intermédiaire — `brief.json`, `outline.json`,
`script.json`, `plan/plan_*.json`, `ir.json`, `renderplan.json` — à côté du `gps.mp4`
final et de ses sidecars `.srt` / `.vtt`, si bien que chaque étape est inspectable et
adressée par contenu. `render` accepte `--engine stub` pour des images en couleur unie
quand on veut exercer le pipeline sans invoquer Manim. `vqa` évalue un plan déjà
compilé à la recherche de défauts `VQA6xx` hors ligne, et `build --vqa` intègre cette
évaluation dans le pipeline, réparant les défauts géométriques qu'il trouve.

`--audio` active la narration : un backend `--tts` (`stub` pour un audio déterministe
hors ligne, `cassette` pour une relecture enregistrée, ou le fournisseur réel `openai`
en option) donne voix à chaque segment, et les durées mesurées deviennent l'autorité
de timing, avec des WAV par segment plus `audio/segments.json` et `audio/metadata.json`
écrits à côté des autres artefacts. `--offline` est une garantie absolue d'absence de
réseau — il épingle le LLM cassette et le TTS stub et refuse de construire un vrai
fournisseur même si l'environnement en réclame un ; l'audio est sinon désactivé par
défaut et retombe sur un timing en mots par minute (`AUD9xx`).

Un IR sémantiquement cassé échoue bruyamment et ne rend rien — le garde-fou sur lequel
repose toute la conception :

```bash
manorem validate examples/gps/ir_broken_ref.json   # exits 1 with an IR2xx error, no video
```

## Développement

`make` sans cible liste tout. Chacune de ces cibles tourne aussi en CI :

| Cible | Rôle |
| --- | --- |
| `make install` | synchronise tous les paquets du workspace et les dépendances de dev |
| `make fmt` | applique le formatage et le tri des imports |
| `make lint` | vérifie formatage et règles de lint, sans écrire |
| `make typecheck` | `mypy --strict` sur les paquets et les tests |
| `make test` | tests rapides — exclut les vrais rendus et tout ce qui exige une clé d'API |
| `make test-slow` | tests de rendu de référence (vrai Manim, plusieurs minutes) |
| `make check` | lint + typecheck + test |

Conventions de test structurelles, et non stylistiques :

- **`tests/support/ir_builders.valid_scene()` doit valider avec zéro diagnostic à tous
  les niveaux.** Si une vérification nouvellement ajoutée s'y déclenche, c'est la
  vérification qui est fausse — pas la fixture. Un validateur qui signale de l'IR
  ordinaire et bien formé est pire qu'inutile : la boucle de réparation brûlera ses
  tentatives à réécrire de l'IR correct.
- **Asserter sur les codes et les pointeurs, jamais sur la formulation du message.**
  Le message est pour les humains et peut être reformulé librement ; le code et le
  JSON Pointer sont le contrat machine dont dépendent l'agent de réparation et
  l'inspecteur.
- **Un défaut produit exactement un constat.** `tests/support/diag.only` échoue quand
  une vérification se déclenche deux fois, car les constats en double saturent la
  boucle de réparation.
- Les tests déclarent exactement leur niveau (`error_codes` / `warning_codes`), pour
  qu'un test sémantique ne soit pas pris en otage par un avertissement de rythme
  incident.

## Règles de conception

L'essentiel des choix non évidents de ce dépôt découle d'une poignée de positions :

- **Vocabulaires fermés.** Types d'objets, opérations, layouts et easings sont tous
  des enums. Le modèle choisit dans un menu que le compilateur comprend forcément ;
  élargir le menu est un acte délibéré — ajouter le membre, ajouter son traitement
  dans le compilateur, ajouter son test.
- **Validation pilotée par tables.** Les opérations déclarent leurs signatures
  (`CORE_OPERATIONS`) : en ajouter une, c'est ajouter une déclaration, pas une branche
  de plus. Le prompt de génération est construit à partir des mêmes déclarations, donc
  le menu du modèle et les règles du validateur ne peuvent pas dériver l'un de l'autre.
- **Adressage par contenu partout.** Les artefacts sont indexés par le sha256 de leur
  JSON canonique, ce qui donne déduplication, versionnage à bas coût et vérifications
  de déterminisme exactes à l'octet. Les solveurs de layout à composante aléatoire
  prennent une graine fixe pour la même raison.
- **Rejeter, pas assainir.** Les clés de stockage malformées et les ids invalides
  lèvent une exception au lieu d'être réécrits en silence — un appelant qui en produit
  a un bug, et le réparer discrètement masque ce bug. `slugify` n'existe que pour les
  noms générés par machine.
- **Les schémas persistés ont une version.** `Project.ir_version` fait qu'un IR stocké
  plus ancien est reconnu et migré plutôt que mal interprété.
- **L'audio fait autorité sur le timing, et n'est pas une seconde timeline.** Lorsque
  la parole synthétisée est disponible, les durées de segment mesurées renseignent les
  champs de timing de narration existants avant la compilation. Le même résolveur de
  timing symbolique pilote donc les cues d'animation, la quantification en images et
  les sous-titres. Les assets audio ne sont rattachés qu'au plan compilé et ne font
  jamais partie du Visual IR.
