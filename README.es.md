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

**Español** · [English](README.md) · [Igbo](README.ig.md) · [Français](README.fr.md) · [简体中文](README.zh-CN.md)

Convierte una idea en un vídeo explicativo narrado — sin dejar que un modelo de
lenguaje escriba código de animación.

La premisa del pipeline es que un LLM es bueno decidiendo *qué debe significar una
escena* y malo decidiendo *dónde va cada cosa*. Así que el modelo nunca emite código
Manim, nunca elige una coordenada y nunca nombra un número de fotograma. Emite
**Visual IR**: un documento fuertemente tipado, validado y versionado que describe
objetos, relaciones, narración e intención temporizada. Un compilador determinista
lo convierte en disposición, keyframes de cámara e instrucciones de render.

Un IR inválido nunca llega al renderer. Esa única regla es la razón de ser de casi
todo este repositorio.

## Estado

El Milestone 1 está completo: los ocho paquetes que la configuración del workspace
anticipa están implementados, y `manorem build` lleva una idea a un vídeo con
subtítulos sin conexión. Lo que existe está completo, estrictamente tipado y
cubierto por pruebas (927 pruebas, `mypy --strict` limpio); nada está simulado
fingiendo ser más de lo que es.

| Paquete | Estado | Contenido |
| --- | --- | --- |
| `manorem-core` | implementado | settings, logging estructurado, el vocabulario de diagnósticos, almacenamiento de objetos, hashing canónico |
| `manorem-ir` | implementado | el Visual IR: modelos, exportación de JSON Schema, validación en tres niveles, resolución simbólica de tiempos |
| `manorem-skills` | implementado | paquetes de vocabulario de dominio (más tipos de objeto, operaciones, restricciones) |
| `manorem-compiler` | implementado | IR → `RenderPlan`: normalización, resolución de layout, tiempos, cámara, autofix |
| `manorem-renderer` | implementado | worker Manim aislado (y un stub) que produce vídeo mudo por escena |
| `manorem-compositor` | implementado | concatenación de escenas, transiciones, timeline de audio, subtítulos SRT/VTT |
| `manorem-ai` | implementado | proveedores (Gemini / casetes grabados / stub), agentes de planificación, reparación acotada |
| `manorem-cli` | implementado | el punto de entrada `manorem`: `build`, `validate`, `compile`, `render`, `schema` |

Honesto sobre los límites: los renders del Milestone 1 **no se evalúan por calidad
visual** — `manorem build` informa `quality=None`, nunca «se ve bien», y la etapa de
Visual QA (`VQA6xx`) está diseñada pero aún no implementada. La validación de
procedencia demuestra que una URL citada se recuperó realmente, **no** que la fuente
respalde la afirmación. No hay TTS: los tiempos de narración se estiman a partir de un
modelo de palabras por minuto, así que el vídeo es mudo pero temporizado y con
subtítulos sincronizados. `examples/scratch/scene.py` es un archivo Manim escrito a
mano que se conserva como referencia, no forma parte del pipeline.

## La forma del conjunto

```
idea ──► story plan ──► visual plan ──► Visual IR ──► validate ──► compile ──► render ──► composite ──► video
                                            ▲            │
                                            └── repair ◄─┘   (acotado, guiado por diagnósticos)
```

Dos propiedades sostienen el diseño.

**El IR es la fuente de la verdad.** Es semántico: un cue `flow` significa «muestra
datos moviéndose de A a B», no `MoveAlongPath`. Las posiciones son *intención*
(`auto`, un slot con nombre, ancladas a otro objeto), no coordenadas. El tiempo es
*simbólico* («cuando empieza la narración sobre satélites»), no segundos. Todo lo
mecánico se deriva aguas abajo, y por eso el mismo IR puede reorientarse a 16:9, 9:16
y 1:1 cambiando un solo campo.

**Los fallos son estructurados, no textuales.** Cada subsistema emite el mismo tipo
`Diagnostic`, direccionado con un JSON Pointer de RFC 6901 y con un código con
espacio de nombres. Eso es lo que hace posible el bucle de reparación: consume
códigos y punteros, no prosa, y está acotado — nunca es un reintento abierto.

## Estructura

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
  cli/src/manorem_cli/           la línea de comandos `manorem`
tests/
  support/                       builders de IR/IA y aserciones de diagnósticos comunes a la suite
  unit/                          por paquete: core, ir, skills, compiler, renderer, compositor, ai, cli
  integration/                   el ejemplo GPS escrito a mano, de principio a fin
examples/gps/                    el Visual IR de referencia: nueve escenas, más un fixture de referencia rota
examples/scratch/                archivo Manim de referencia, excluido del lint
```

No existe una distribución raíz a propósito: cada unidad de código vive en
`packages/*` para que el worker de render aislado pueda instalar el motor sin
arrastrar dependencias de API o de servicios. Los imports relativos que cruzan
fronteras de paquete están prohibidos por el lint, así que el grafo de dependencias
se mantiene acíclico y legible — `manorem_core` no sabe nada de Manim, de
proveedores de LLM ni del IR.

## El Visual IR

Un `Project` contiene `Episode`s, que contienen `Scene`s. La escena es la unidad de
autoría, generación, render, caché y reparación: es autocontenida y no referencia
nada fuera de sí misma, y eso es lo que hace viable la generación por IA escena a
escena (los límites de anidamiento de la salida estructurada descartan generar el
proyecto entero) y la reparación local — un parche que arregla la escena 4 no puede
perturbar la escena 7.

Dentro de una escena:

- **objects** — un conjunto cerrado de tipos semánticos (`text`, `math`, `chart`,
  `globe`, `network`, …), cada uno con su modelo de props tipado, de modo que «un
  chart sin series» es un error de schema y no un crash del renderer
- **placement** — `auto` (decide el motor de layout), `slot`, `anchor` (relativo a
  otro objeto) o coordenadas `stage` explícitas como vía de escape
- **layout** — intención declarada (`grid`, `radial`, `tree`, `split`, …), resuelta
  más tarde
- **relationships** — aristas tipadas que alimentan los solvers de layout, las
  restricciones de las skills y a veces la geometría (`points_to` se vuelve una flecha)
- **narration** — segmentos con roles (`hook`, `revelation`, `payoff`, …); los
  tiempos se derivan, nunca se escriben a mano
- **timeline** — `Cue`s: una operación semántica, sus objetivos, cuándo empieza,
  cuánto dura y *por qué* existe
- **camera** — una pose inicial más límites; los *movimientos* de cámara son cues
  ordinarios, así que pueden ordenarse y anclarse en el tiempo respecto a lo visual

Las posiciones viven en el **stage space**: `[-1, 1]` en ambos ejes, donde el
cuadrado unidad es el área segura visible en cualquier relación de aspecto. Ninguna
coordenada de mundo y ninguna constante 16:9 aparece en ningún punto anterior al paso
del compilador que mapea el stage space a unidades de Manim.

### Crear una escena

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
project.content_hash()          # '5446673f6e6d...' — el mismo IR da el mismo hash
```

Nada de esto dice dónde se sitúa el título, cuándo han pasado 1,4 segundos ni qué
clase de Manim dibuja un punto. Todos los modelos son inmutables (`frozen`), así que
un paso del compilador produce un documento nuevo en lugar de mutar el que recibió.

### En tránsito

Los modelos *son* el schema. `manorem_ir.schema` exporta JSON Schema para `Project`
y `Scene`, calcula su digest para detectar deriva, y es la fuente prevista para los
tipos TypeScript del IR y para la petición de salida estructurada que se envía al
modelo. Dos sistemas de tipos mantenidos a mano divergen; uno generado a partir del
otro no puede.

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

Los parámetros de un cue están restringidos a escalares JSON planos — una frontera
de seguridad estructural, no procedimental. Un parámetro no puede ser una estructura
anidada ni una expresión, así que nada puede colar comportamiento hacia el renderer.
Una skill que necesite una configuración más rica declara un nuevo tipo de objeto en
su lugar.

## Validación

Tres niveles, cada uno informando allí donde el fallo es realmente detectable:

- **T1 estructural** — la forma del documento. Pydantic cubre tipos, rangos y
  discriminadores; este nivel añade lo que un schema no puede expresar: ids
  duplicados, escenas vacías, duraciones que se cuantizan a cero fotogramas a la tasa
  objetivo (el mismo IR está bien a 60fps y degenera a 15fps).
- **T2 referencial / semántico** — si el documento *significa* algo. Toda referencia
  resuelve, toda firma de operación se satisface, la timeline es acíclica, nada se usa
  antes de mostrarse.
- **T3 ritmo y geometría** — bien formado pero cuestionable: silencios muertos,
  escenario abarrotado, objetos solapados o fuera del escenario, narración que
  desborda su escena. Avisos por defecto, promocionables a errores por política.

Los tres se computan a partir del IR y del plan resuelto, nunca de píxeles.
Establecen que un plan está *bien formado*, que es una afirmación distinta de *se ve
bien* — el juicio perceptual pertenece a la etapa de Visual QA y a sus códigos
`VQA6xx`.

Un hallazgo nombra un código, una severidad y un puntero al documento infractor. Dada
la escena de arriba con el cue `pulse` mal escrito, apuntando a `"phones"`:

```python
>>> for d in validate_scene(broken):
...     print(d)
error: IR201_UNKNOWN_OBJECT_REF [intro] at /timeline/2/targets/0: cue 'pulse' targets unknown object 'phones'
```

Los códigos llevan el espacio de nombres de la etapa que los emite:

| Rango | Etapa |
| --- | --- |
| `IR1xx` | estructural |
| `IR2xx` | referencial / semántico |
| `IR3xx` | lints de ritmo y geometría |
| `CMP4xx` | compilación |
| `RND5xx` | render |
| `VQA6xx` | calidad visual (reservado) |
| `MUX7xx` | composición |
| `RES8xx` | procedencia de investigación |

Todos los códigos `IR2xx` están en `SEMANTIC_ERROR_CODES`, y al autofix determinista
le está prohibido tocar ese conjunto — en su lugar escala al agente de reparación
acotado. «Arreglar» en silencio una referencia colgante descarta la intención autoral
y esconde un defecto real del planificador detrás de un render de aspecto plausible.
`Diagnostic.autofixable` se deriva de ese conjunto en vez de almacenarse, así que
quien construye un diagnóstico no puede reetiquetar un error semántico como inocuo.

La resolución de tiempos vive en `manorem_ir.resolve` y no en el compilador porque
dos consumidores la necesitan y no deben discrepar: los validadores T2/T3 y el paso
del compilador que cuantiza esos mismos números a fotogramas. La resolución itera
hasta un punto fijo en lugar de ordenar topológicamente, así que una timeline
parcialmente rota sigue dando tiempos útiles para los cues bien formados — lo que
mantiene los diagnósticos específicos en vez de colapsar en un único «la timeline
está rota».

## Primeros pasos

Requiere Python ≥ 3.13 (el repo fija 3.14) y [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-packages
```

```bash
make test
```

La configuración se rige por el entorno con el prefijo `MANOREM_`; copia
`.env.example` a `.env` y edítalo. Los valores por defecto están elegidos para
funcionar sin conexión: el proveedor de LLM es `cassette` (reproduce respuestas
grabadas, sin clave de API), la calidad de render es `draft` y el bucle de reparación
hace como máximo 2 intentos.

## Uso de la CLI

`manorem` son cinco verbos sobre un único pipeline. `validate` y `compile` operan
sobre un proyecto Visual IR, `render` sobre un `RenderPlan` compilado, `schema`
exporta el JSON Schema, y `build` ejecuta todo el pipeline de idea a vídeo sin
conexión.

```bash
manorem validate examples/gps/ir.json
manorem compile examples/gps/ir.json --aspect 16:9 -o plan.json
manorem render plan.json --quality draft -o gps.mp4
manorem build "How GPS determines your location." --aspect 16:9 -o out/
```

`build` escribe cada artefacto intermedio — `brief.json`, `outline.json`,
`script.json`, `plan/plan_*.json`, `ir.json`, `renderplan.json` — junto al `gps.mp4`
final y sus sidecars `.srt` / `.vtt`, de modo que cada etapa es inspeccionable y
está direccionada por contenido. `render` acepta `--engine stub` para fotogramas de
color sólido cuando quieres ejercitar el pipeline sin invocar Manim.

Un IR semánticamente roto falla de forma ruidosa y no renderiza nada — la barrera
de seguridad sobre la que gira todo el diseño:

```bash
manorem validate examples/gps/ir_broken_ref.json   # exits 1 with an IR2xx error, no video
```

## Desarrollo

`make` sin objetivo lista todo. Cada uno de estos también se ejecuta en CI:

| Objetivo | Qué hace |
| --- | --- |
| `make install` | sincroniza todos los paquetes del workspace y las dependencias de desarrollo |
| `make fmt` | aplica formato y ordena imports |
| `make lint` | comprueba formato y reglas de lint, sin escribir |
| `make typecheck` | `mypy --strict` sobre paquetes y pruebas |
| `make test` | pruebas rápidas — excluye renders reales y todo lo que necesite una clave de API viva |
| `make test-slow` | pruebas de render de referencia (Manim real, minutos) |
| `make check` | lint + typecheck + test |

Convenciones de pruebas que son estructurales, no estilísticas:

- **`tests/support/ir_builders.valid_scene()` debe validar con cero diagnósticos en
  todos los niveles.** Si una comprobación recién añadida salta sobre ella, la
  comprobación está mal — no el fixture. Un validador que marca IR ordinario y bien
  formado es peor que inútil, porque el bucle de reparación quemará sus intentos
  acotados reescribiendo IR correcto.
- **Aserta sobre códigos y punteros, nunca sobre la redacción del mensaje.** El
  mensaje es para humanos y puede reescribirse libremente; el código y el JSON Pointer
  son el contrato de máquina del que dependen el agente de reparación y el inspector.
- **Un fallo produce exactamente un hallazgo.** `tests/support/diag.only` falla cuando
  una comprobación salta dos veces, porque los hallazgos duplicados inundan el bucle
  de reparación.
- Las pruebas declaran su propio nivel con exactitud (`error_codes` /
  `warning_codes`), para que una prueba semántica no quede secuestrada por un aviso de
  ritmo incidental.

## Reglas de diseño

Casi todas las decisiones no obvias de este repositorio se siguen de un puñado de
posturas:

- **Vocabularios cerrados.** Los tipos de objeto, las operaciones, los layouts y los
  easings son todos enums. El modelo elige de un menú que el compilador entiende con
  garantía; ensanchar el menú es un acto deliberado — añade el miembro, añade su
  manejo en el compilador, añade su prueba.
- **Validación dirigida por tablas.** Las operaciones declaran sus firmas
  (`CORE_OPERATIONS`), así que añadir una significa añadir una declaración, no otra
  rama. El prompt de generación se construye con esas mismas declaraciones, así que el
  menú del modelo y las reglas del validador no pueden separarse.
- **Direccionamiento por contenido en todas partes.** Los artefactos se indexan por el
  sha256 de su JSON canónico, lo que da deduplicación, versionado barato y
  comprobaciones de determinismo exactas al byte. Los solvers de layout con componente
  aleatorio toman una semilla fija por la misma razón.
- **Rechaza, no sanees.** Las claves de almacenamiento malformadas y los ids inválidos
  lanzan excepción en vez de reescribirse en silencio — quien las produce tiene un bug,
  y repararlo calladamente esconde ese bug. `slugify` existe solo para nombres
  generados por máquina.
- **Los schemas persistidos llevan versión.** `Project.ir_version` implica que el IR
  almacenado más antiguo se reconoce y se migra en vez de malinterpretarse.
