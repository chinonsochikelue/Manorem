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

**Igbo** · [English](README.md) · [Español](README.es.md) · [Français](README.fr.md) · [简体中文](README.zh-CN.md)

*Okwu nkà ndị dịka compiler, renderer, schema na cue ka a hapụrụ na Bekee, n'ihi na
ha bụ aha e ji na koodu ahụ.*

Mee ka echiche ghọọ vidiyo nkọwa nwere olu na-akọ ya — n'ekweghị ka ụdị asụsụ (LLM)
dee koodu animeshọn.

Ntọala usoro a bụ nke a: LLM mara nke ọma ikpebi *ihe scene kwesịrị ịpụta*, ma
amaghị nke ọma ikpebi *ebe ihe ga-adị*. Ya mere ụdị ahụ anaghị edepụta koodu Manim,
ọ naghị ahọrọ coordinate, ọ naghị akpọkwa nọmba frame. Ihe ọ na-edepụta bụ **Visual
IR**: akwụkwọ e depụtara ụdị ya n'ụzọ siri ike, nke a nyochara, nke nwere vezọn,
na-akọwa objects, mmekọrịta, okwu nkọwa na ebumnuche e kenyere oge. Compiler
na-eme otu ihe ahụ mgbe niile na-atụgharị nke ahụ ghọọ nhazi, camera keyframes na
ntụziaka nrenda.

IR na-ezighị ezi anaghị eru renderer aka. Otu iwu ahụ bụ ihe kpatara ọtụtụ ihe dị
na repository a.

## Ọnọdụ

Ọ zuola Milestone 1 ruo 3: ngwugwu asatọ niile nke nhazi workspace na-atụ anya ka
arụzuru, `manorem build` na-ewere echiche ruo vidiyo nwere ederede n'enweghị
ịntanetị ma nwee ike mepụta ụda okwu nkọwa site n'ụzọ TTS stub/cassette ya nke
na-emepụta otu ihe mgbe niile, Visual QA (`VQA6xx`) na-enyocha vidiyo e mechara maka ntụpọ
geometry ma bughachi ha na nrụzi IR, na okwu e mepụtara site n'igwe — mgbe a
kwadoro ya — na-aghọ ikike oge nke a na-ahazi vidiyo dum dabere na ya. Ihe dị adị
zuru ezu, e depụtara ụdị ya n'ụzọ siri ike, e nwekwara nnwale maka ya (nnwale
1,000+, `mypy --strict` dị ọcha); ihe na-adịghị adị, a naghị eme ka o yie ka ọ dị
adị.

| Ngwugwu | Ọnọdụ | Ihe dị n'ime |
| --- | --- | --- |
| `manorem-core` | arụzuru | settings, structured logging, okwu diagnostic, nchekwa object, canonical hashing |
| `manorem-ir` | arụzuru | Visual IR: models, mbupụ JSON Schema, nnyocha ọkwa atọ, idozi oge site n'akara |
| `manorem-skills` | arụzuru | ngwugwu okwu maka ngalaba (ụdị object ọzọ, ọrụ, mmachi) |
| `manorem-compiler` | arụzuru | IR → `RenderPlan`: nhazi, idozi layout, oge, camera, autofix |
| `manorem-renderer` | arụzuru | onye ọrụ Manim e kpuchiri (na stub) nke na-emepụta vidiyo maka scene ọ bụla, gbakwụnye Visual QA geometry |
| `manorem-compositor` | arụzuru | ijikọta scene, mgbanwe, timeline ụda, njikọ A/V, ederede SRT/VTT |
| `manorem-ai` | arụzuru | ndị na-eweta LLM (Gemini / Anthropic / OpenAI / key-pool failover / cassette e dekọrọ / stub) na ndị na-eweta TTS (stub / cassette / okwu dakọtara OpenAI), ndị agent nhazi atụmatụ, nrụzi nwere oke |
| `manorem-cli` | arụzuru | ọnụ ụzọ `manorem`: `build`, `validate`, `compile`, `render`, `vqa`, `schema` |

Eziokwu banyere akụkụ ọnụ: Visual QA na-atụ **ntụpọ geometry** — ederede pụọ na
stage, ihe na-akpakọrịta, ederede pere mpe nke a na-apụghị ịgụ, ọdịiche ụcha adịghị
mma megide background e kwuru — ọ bụghị ogo nka; e nweghị "visual quality score" ọ
bụla n'ozuzu ya n'ụzọ e ji aka mee, ọ bụ na akụkọ dị ọcha pụtara *ọ dịghị ntụpọ a
tụrụ*, ọ bụghị *ezigbo vidiyo*. Ọ gwụghị ma a rịọ ya ka ọ nyochaa
(`manorem build --vqa`), vidiyo ka na-akọ `quality=None` kama ị sị "ọ mara mma".
Nnyocha provenance na-egosi na e nwetara URL e hotara n'ezie, **ọ bụghị** na isi
mmalite ahụ na-akwado nkwuwa okwu ahụ. A pụrụ iji igwe mepụta okwu nkọwa ma ọ bụ
hapụ ya ka ọ gbachie nkịtị: site na `--audio`, onye na-eweta ederede-ruo-okwu
na-enye akụkụ ọ bụla olu, ogologo oge ya *nke a tụrụ* na-eduzi windo okwu nkọwa,
ebe a na-anya cue na ederede — ụda bụ ikike oge. Enweghị ụda — nke bụ ndabere,
`--no-audio`, ma ọ bụ mgbe mmepụta na-adịghị — oge okwu nkọwa na-alaghachi na atụmatụ
okwu-kwa-nkeji, ya mere vidiyo ahụ na-anọgide na-agbachi nkịtị mana e kenyere ya oge
nwere ederede a hazikọtara. Ọdịda mmepụta na-alaghachi kwa scene ma bụrụ ihe a na-ahụ
anya site na diagnostic `AUD9xx`.
`examples/scratch/scene.py` bụ faịlụ Manim e ji aka dee, e debere ya maka ntụaka, ọ
bụghị akụkụ nke usoro a.

## Ọdịdị nke ihe ahụ

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

A na-emepụta okwu nkọwa *tupu* e chịkọta ya: ogologo oge kwa akụkụ a tụrụ na-edegharị
windo okwu nkọwa, ya mere compiler na-aghọ ezigbo oge kama atụmatụ. Mgbe ụda
gbanyụrụ, a na-amafe nzọụkwụ ahụ, windo ndị ahụ na-anọgidekwa na atụmatụ
okwu-kwa-nkeji — otu ụzọ ahụ, otu nkewa tupu ya.

Ihe abụọ na-ejide imewe a ọnụ.

**IR bụ isi eziokwu.** O nwere nkọwa: `flow` cue pụtara "gosi data si A gaa B", ọ
bụghị `MoveAlongPath`. Ebe ihe nọ bụ *ebumnuche* (`auto`, slot nwere aha, ma ọ bụ
nke e jikọtara na object ọzọ), ọ bụghị coordinate. Oge bụ *akara* ("mgbe okwu nkọwa
gbasara satellite na-amalite"), ọ bụghị sekọnd. A na-enweta ihe niile bụ nke igwe
n'okpuru, nke mere na otu IR ahụ nwere ike gbanwee gaa 16:9, 9:16 na 1:1 site
n'ịgbanwe otu field.

**Ọdịda nwere nhazi, ọ bụghị naanị ederede.** Akụkụ ọ bụla na-emepụta otu ụdị
`Diagnostic` ahụ, nke e ji JSON Pointer nke RFC 6901 gosi ebe ọ dị, nke nwere koodu
e kenyere namespace. Nke ahụ bụ ihe na-eme ka usoro nrụzi kwe omume: ọ na-eri koodu
na pointer, ọ bụghị okwu ọnụ, ma o nwere oke — ọ dịghị mgbe ọ na-anwa ya n'enweghị
njedebe.

## Nhazi

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
  cli/src/manorem_cli/           ahịrị iwu `manorem`
tests/
  support/                       ndị na-ewu IR/AI na nkwenye diagnostic nke nnwale niile ji
  unit/                          kwa ngwugwu: core, ir, skills, compiler, renderer, compositor, ai, cli
  integration/                   ọmụmaatụ GPS e ji aka dee, site na mmalite ruo ọgwụgwụ
examples/gps/                    Visual IR ntụaka: scene itoolu, gbakwụnye broken-reference fixture
examples/scratch/                faịlụ Manim ntụaka, e wepụrụ ya na lint
```

Ọ dịghị root distribution na ebumnuche: koodu ọ bụla dị na `packages/*` ka onye ọrụ
nrenda e kpuchiri nwee ike wụnye injin ahụ n'akpọghị API ma ọ bụ service
dependencies. Lint machibidoro relative imports gafere oke ngwugwu, ya mere graph
dependency na-anọgide na-enweghị okirikiri ma dị mfe ịgụ — `manorem_core` amaghị ihe
ọ bụla gbasara Manim, ndị na-eweta LLM ma ọ bụ IR.

## Visual IR

`Project` na-ejide `Episode`, nke na-ejide `Scene`. Scene bụ nkeji nke ide, nke
imepụta, nke nrenda, nke caching na nke nrụzi: o zuru onwe ya, ọ naghị ezo aka na
ihe ọ bụla dị ya n'èzí — nke ahụ mere na imepụta scene otu otu site n'AI kwere omume
(oke nesting nke structured output na-egbochi imepụta project dum), na na nrụzi
na-adị n'otu ebe — patch na-edozi scene 4 apụghị imetụ scene 7 aka.

N'ime scene:

- **objects** — ụdị nwere nkọwa nke e mechiri (`text`, `math`, `chart`, `globe`,
  `network`, …), nke ọ bụla nwere props model e depụtara ụdị ya, ya mere "chart
  na-enweghị series" bụ njehie schema kama ịbụ ọdịda renderer
- **placement** — `auto` (layout engine na-ekpebi), `slot`, `anchor` (n'ebe object
  ọzọ dị), ma ọ bụ coordinate `stage` doro anya dịka ọnụ ụzọ mgbapụ
- **layout** — ebumnuche e kwuru (`grid`, `radial`, `tree`, `split`, …), a na-edozi
  ya ma emesịa
- **relationships** — njikọ e depụtara ụdị ya nke na-enye layout solvers, mmachi
  skill, na mgbe ụfọdụ geometry ike (`points_to` na-aghọ akụ)
- **narration** — akụkụ nwere ọrụ (`hook`, `revelation`, `payoff`, …); a na-esite na
  ha nweta oge, a naghị ede ya
- **timeline** — `Cue` ndị: otu ọrụ nwere nkọwa, ihe ọ na-eche, mgbe ọ na-amalite,
  ogologo oge ọ na-adị, na *ihe kpatara* ọ dị
- **camera** — ọnọdụ mbụ na mmachi; ịkwaga camera bụ cue nkịtị, ya mere e nwere ike
  hazie ya ma kenye ya oge megide ihe a na-ahụ anya

Ebe ihe nọ dị na **stage space**: `[-1, 1]` n'akụkụ abụọ, ebe unit square bụ ebe
nchekwa a na-ahụ anya n'ụdị aspect ratio ọ bụla. Ọ dịghị coordinate ụwa ma ọ bụ
constant 16:9 ọ bụla pụtara n'ebe ọ bụla n'elu compiler pass nke na-atụgharị stage
space ka ọ bụrụ nkeji Manim.

### Ide scene

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
project.content_hash()          # '5446673f6e6d...' — otu IR na-enye otu hash mgbe niile
```

Ọ dịghị ihe ebe a na-ekwu ebe title ga-anọ, mgbe sekọnd 1.4 gafere, ma ọ bụ klas
Manim nke na-ese dot. Model ọ bụla bụ nke a kpọchiri (`frozen`), ya mere compiler
pass na-emepụta akwụkwọ ọhụrụ kama ịgbanwe nke e nyere ya.

### Ụdị a na-eziga

Model ndị ahụ *bụ* schema. `manorem_ir.schema` na-ebupụ JSON Schema maka `Project`
na `Scene`, na-agụta digest ya iji chọpụta mgbanwe, ma bụrụkwa ebe e bu n'obi isite
nweta ụdị IR nke TypeScript na arịrịọ structured output a na-ezigara ụdị ahụ.
Sistemụ ụdị abụọ e ji aka na-elekọta na-esi ike ịkwekọ; nke e sitere na nke ọzọ
mepụta enweghị ike ịpụ n'ụzọ.

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

Params nke cue bụ naanị JSON scalar dị larịị — nke ahụ bụ oke nchekwa nke nhazi, ọ
bụghị nke usoro. Param apụghị ịbụ nhazi dị n'ime nhazi ma ọ bụ expression, ya mere ọ
dịghị ihe pụrụ izo omume banye n'ebe renderer nọ. Skill chọrọ nhazi buru ibu karịa
na-ekwupụta ụdị object ọhụrụ kama.

## Nnyocha

Ọkwa atọ, nke ọ bụla na-akọ n'ọkwa ebe a pụrụ ịchọpụta ntụpọ n'ezie:

- **T1 structural** — ọdịdị akwụkwọ ahụ. Pydantic na-elekọta ụdị, oke na
  discriminator; ọkwa a na-agbakwụnye ihe schema apụghị ikwu: id ndị dị ugboro abụọ,
  scene tọgbọrọ chakoo, oge ndị na-aghọ frame efu n'ọnụ ọgụgụ frame a chọrọ (otu IR
  ahụ dị mma na 60fps ma bụrụ ihe efu na 15fps).
- **T2 referential / semantic** — ma akwụkwọ ahụ *pụtara* ihe ọ bụla. Ntụaka ọ bụla
  na-ezute ihe, mbinye aka ọrụ ọ bụla zuru, timeline enweghị okirikiri, a naghị eji
  ihe tupu e gosi ya.
- **T3 pacing na geometry** — o zuru ezu ma jụọ ajụjụ: oge efu, stage juru eju,
  objects na-akpakọ ma ọ bụ na-apụ n'èzí, okwu nkọwa na-agabiga ogologo scene.
  Ịdọ aka ná ntị ka ọ bụ, mana iwu nwere ike mee ka ọ bụrụ njehie.

A na-esite na IR na plan e dozirila gụta ha atọ, ọ bụghị site na pixel. Ha na-egosi
na plan *zuru ezu n'ọdịdị*, nke dị iche na ikwu na *ọ mara mma* — ma frame e mechara
ọ na-apụta nke ọma ka a na-atụ mgbe nrenda gasịrị site na ọkwa Visual QA na koodu
`VQA6xx` ya.

Ihe a chọpụtara na-akpọ koodu, ogo njehie, na pointer n'ime akwụkwọ mejọrọ. Were
scene dị n'elu ebe e dehiere `pulse` cue ka o chee `"phones"`:

```python
>>> for d in validate_scene(broken):
...     print(d)
error: IR201_UNKNOWN_OBJECT_REF [intro] at /timeline/2/targets/0: cue 'pulse' targets unknown object 'phones'
```

Koodu ọ bụla nwere namespace nke ọkwa welitere ya:

| Oke | Ọkwa |
| --- | --- |
| `IR1xx` | structural |
| `IR2xx` | referential / semantic |
| `IR3xx` | pacing na geometry lints |
| `CMP4xx` | compile |
| `RND5xx` | render |
| `VQA6xx` | visual quality |
| `MUX7xx` | ijikọta |
| `RES8xx` | provenance nnyocha |
| `AUD9xx` | ụda okwu nkọwa / oge |

Koodu `IR2xx` ọ bụla dị na `SEMANTIC_ERROR_CODES`, e machibidokwara autofix ka ọ
ghara imetụ set ahụ aka — ọ na-ebuga ya n'aka onye ọrụ nrụzi nwere oke. Ị "dozie"
ntụaka na-adịghị adị na nzuzo na-atụfu ebumnuche onye dere ya ma zoo ntụpọ planner
dị adị n'azụ vidiyo nke yiri ka ọ dị mma. `Diagnostic.autofixable` na-esite na set
ahụ pụta, ọ bụghị ihe e chekwara, ya mere onye na-emepụta diagnostic apụghị ịkpọ
njehie semantic ihe na-emerụghị ahụ.

Idozi oge dị na `manorem_ir.resolve` kama ịdị na compiler n'ihi na ndị ọrụ abụọ
chọrọ ya, ha ekwesịghịkwa ikwu ihe dị iche: ndị nyocha T2/T3 na compiler pass nke
na-atụgharị otu ọnụ ọgụgụ ahụ ka ọ bụrụ frame. Idozi na-agagharị ruo mgbe o kwụsịrị
otu ebe kama ịhazi ya n'usoro topological, ya mere timeline mebiri ụfọdụ na-enyekwa
oge bara uru maka cue ndị zuru ezu — nke ahụ na-eme ka diagnostic pụta ìhè kama ịbụ
naanị "timeline mebiri".

### Ikike oge ụda

Mgbe a kwadoro ụda, a na-emepụta akụkụ okwu nkọwa ọ bụla n'onwe ya. A na-etinye
ogologo oge a tụrụ nke clip ọ bụla n'ime field `NarrationSegment.start/end` dị adị
tupu e chịkọta ya. A na-ahazi akụkụ ndị ahụ otu n'elu ibe ya n'ime scene ha, gụnyere
`pause_after` nke akụkụ ọ bụla.

Sistemụ oge nke akara dị adị na-edozi `at_narration(...)` megide windo ndị ahụ a
tụrụ. Ya mere compiler achọghị mgbagha oge nkeiche maka ụda: ezigbo oge okwu nkọwa
na-agafe otu ụzọ idozi ahụ nke atụmatụ WPM na-eji. Compositor na-emesịa jikọọ akụ ụda
kwekọrọ na `AudioCue` ndị e chịkọtara ma rụọ njikọ A/V ikpeazụ.

Ọ dịghị timeline ụda nke abụọ, ọ dịghịkwa elekere ederede nke abụọ.

## Mmalite

Ọ chọrọ Python ≥ 3.13 (repository a kwụsịrị na 3.14) na
[uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-packages
```

```bash
make test
```

A na-esite na environment hazie ya, prefix ya bụ `MANOREM_`; detuo `.env.example`
gaa `.env` ma dezie ya. E họọrọ ihe ndị dị na ntọala ka ha rụọ ọrụ n'enweghị
ịntanetị: onye na-eweta LLM bụ `cassette` (na-akpọghachi nzaghachi e dekọrọ, ọ dịghị
chọ API key), ogo nrenda bụ `draft`, ma usoro nrụzi na-agbalị ihe kacha 2.

## Iji CLI

`manorem` bụ ngwaa isii n'otu usoro. `validate` na `compile` na-arụ ọrụ na project
Visual IR, `render` na `vqa` na-arụ na `RenderPlan` e chịkọtara, `schema` na-ebupụ
JSON Schema, `build` na-agba usoro echiche-ruo-vidiyo dum, ebe a na-enweta ọrụ
n'enweghị ịntanetị dịka ụzọ siri ike nke enweghị netwọk.

```bash
manorem validate examples/gps/ir.json
manorem compile examples/gps/ir.json --aspect 16:9 -o plan.json
manorem render plan.json --quality draft -o gps.mp4
manorem vqa plan.json
manorem build "How GPS determines your location." --aspect 16:9 --vqa -o out/
manorem build "How GPS determines your location." --audio --tts stub --offline -o out/
manorem build "How GPS determines your location." --no-audio --offline -o out/
```

`build` na-ede artifact etiti ọ bụla — `brief.json`, `outline.json`, `script.json`,
`plan/plan_*.json`, `ir.json`, `renderplan.json` — n'akụkụ `gps.mp4` ikpeazụ na
sidecar `.srt` / `.vtt` ya, ya mere e nwere ike nyochaa ọkwa ọ bụla ma e ji ọdịnaya
kpọọ ya. `render` na-anabata `--engine stub` maka frame agba siri ike mgbe ị chọrọ
ịnwale usoro ahụ n'akpọghị Manim. `vqa` na-atụ plan e chịkọtaralarị maka ntụpọ
`VQA6xx` n'enweghị ịntanetị, `build --vqa` na-etinyekwa ntụle ahụ n'ime usoro ahụ,
na-edozi ntụpọ geometry ọ chọtara.

`--audio` na-agbanye okwu nkọwa: backend `--tts` (`stub` ụda n'enweghị ịntanetị nke
na-emepụta otu ihe mgbe niile, `cassette` nkpọghachi ihe e dekọrọ, ma ọ bụ ezigbo
onye na-eweta `openai` nke ị họrọ itinye) na-enye akụkụ ọ bụla olu, ogologo oge ndị
a tụrụ na-aghọkwa ikike oge, ebe e dere WAV kwa akụkụ tinyere `audio/segments.json`
na `audio/metadata.json` n'akụkụ artifact ndị ọzọ. `--offline` bụ nkwa siri ike nke
enweghị netwọk — ọ na-ejide cassette LLM na stub TTS ma jụ iwulite ezigbo onye
na-eweta ọbụlagodi ma environment rịọ ya; ma ọ bụghị otú ahụ, ụda gbanyụrụ site na
ntọala ma na-alaghachi na oge okwu-kwa-nkeji (`AUD9xx`).

IR mebiri emebi na semantic na-ada n'ụzọ doro anya ma ọ dịghị ihe ọ na-emepụta —
nchebe nke imewe dum dabere na ya:

```bash
manorem validate examples/gps/ir_broken_ref.json   # exits 1 with an IR2xx error, no video
```

## Mmepe

`make` na-enweghị target na-edepụta ihe niile. Nke ọ bụla n'ime ndị a na-agbakwa
na CI:

| Target | Ihe ọ na-eme |
| --- | --- |
| `make install` | jikọta ngwugwu workspace niile na dependencies mmepe |
| `make fmt` | tinye nhazi na ịhazi imports |
| `make lint` | lelee nhazi na iwu lint, ọ naghị ede ihe |
| `make typecheck` | `mypy --strict` n'elu ngwugwu na nnwale |
| `make test` | nnwale ngwa ngwa — ewepụrụ ezigbo nrenda na ihe ọ bụla chọrọ API key dị ndụ |
| `make test-slow` | nnwale nrenda golden (ezigbo Manim, nkeji ole na ole) |
| `make check` | lint + typecheck + test |

Iwu nnwale ndị na-akwado ụlọ, ọ bụghị nke ejiji:

- **`tests/support/ir_builders.valid_scene()` ga-agafe nnyocha n'enweghị diagnostic ọ
  bụla n'ọkwa niile.** Ọ bụrụ na nyocha ọhụrụ e tinyere na-akụ ya, nyocha ahụ ezighi
  ezi — ọ bụghị fixture. Onye nyocha na-akụ IR nkịtị zuru ezu dị njọ karịa ihe
  na-abaghị uru, n'ihi na usoro nrụzi ga-eji mgbalị ole o nwere dezie IR ziri ezi.
- **Kwenye na koodu na pointer, ọ bụghị otú e siri dee ozi ahụ.** Ozi ahụ dị maka
  mmadụ, e nwere ike dezie ya mgbe ọ bụla; koodu na JSON Pointer bụ nkwekọrịta igwe
  nke onye ọrụ nrụzi na inspector na-adabere na ya.
- **Otu ntụpọ na-emepụta naanị otu ihe a chọpụtara.** `tests/support/diag.only`
  na-ada mgbe nyocha kụrụ ugboro abụọ, n'ihi na ihe a chọpụtara ugboro abụọ na-eju
  usoro nrụzi.
- Nnwale ọ bụla na-akọ ọkwa nke ya kpọmkwem (`error_codes` / `warning_codes`) ka
  nnwale semantic ghara ịbụ ohu nke ịdọ aka ná ntị pacing bịara na mberede.

## Iwu imewe

Ihe ka ọtụtụ n'ime nhọrọ ndị na-adịghị mfe ịghọta na repository a sitere n'obere
ntụziaka ndị a:

- **Okwu ndị e mechiri.** Ụdị object, ọrụ, layout na easing niile bụ enum. Ụdị ahụ
  na-ahọrọ site na menu nke a maara na compiler ga-aghọta; ịgbasa menu ahụ bụ ihe e
  ji aka mee — tinye member ahụ, tinye otú compiler ga-esi jiri ya, tinye nnwale ya.
- **Nnyocha e sitere na tebụl.** Ọrụ ndị ahụ na-ekwupụta mbinye aka ha
  (`CORE_OPERATIONS`), ya mere itinye otu ọrụ pụtara itinye nkwupụta, ọ bụghị alaka
  ọzọ. E ji otu nkwupụta ahụ ewu prompt nke mmepụta, ya mere menu nke ụdị ahụ na iwu
  nke onye nyocha apụghị ịkewa.
- **Content addressing n'ebe niile.** A na-eji sha256 nke canonical JSON ha akpọ
  artifact, nke na-enye mwepụ oyiri, versioning dị ọnụ ala, na nnyocha determinism
  ziri ezi ruo na byte. Layout solver nwere akụkụ na-agba chọọchọọ na-ewere seed a
  kpọchiri maka otu ihe ahụ.
- **Jụ ya kama ịdozi ya.** Storage key mebiri emebi na id na-ezighị ezi na-ebuli
  njehie kama ka e dezie ha na nzuzo — onye kpọrọ ya nwere ntụpọ, idozi ya na nzuzo
  na-ezo ntụpọ ahụ. `slugify` dị naanị maka aha igwe mepụtara.
- **Schema ndị a na-echekwa nwere vezọn.** `Project.ir_version` pụtara na a na-amata
  IR ochie e chekwara ma kwaga ya kama ịkọwa ya n'ụzọ na-ezighị ezi.
- **Ụda bụ ikike oge, ọ bụghị timeline nke abụọ.** Mgbe okwu e mepụtara site n'igwe
  dị, ogologo oge akụkụ a tụrụ na-ejupụta field oge okwu nkọwa dị adị tupu e chịkọta
  ya. Ya mere otu onye na-edozi oge nke akara ahụ na-eduzi cue animeshọn, nghọ frame
  na ederede. A na-ejikọ akụ ụda naanị na plan e chịkọtara, ọ naghị abụkwa akụkụ nke
  Visual IR.
