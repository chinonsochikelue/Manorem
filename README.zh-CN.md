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

**简体中文** · [English](README.md) · [Igbo](README.ig.md) · [Español](README.es.md) · [Français](README.fr.md)

把一个想法变成带旁白的讲解视频——同时不让语言模型编写动画代码。

整条流水线的前提是：LLM 擅长决定*一个 scene 应该表达什么*，不擅长决定*东西该放在哪里*。
所以模型从不输出 Manim 代码，从不挑选坐标，也从不指定帧号。它输出的是 **Visual IR**：
一份强类型、经过校验、带版本号的文档，描述对象、关系、旁白和带时间的意图。再由一个确定性
编译器把它变成布局、相机关键帧和渲染指令。

非法的 IR 永远到不了 renderer。整个仓库的大部分内容，都是为了执行这一条规则而存在的。

## 现状

里程碑 1 已完成：workspace 预留的 8 个包已全部实现，`manorem build` 可以离线地把一个想法
变成带字幕的视频。已存在的部分是完整的、严格类型化的、有测试覆盖的（927 个测试，
`mypy --strict` 无告警）；没有任何空壳假装自己比实际更完整。

| 包 | 状态 | 内容 |
| --- | --- | --- |
| `manorem-core` | 已实现 | settings、结构化日志、诊断词汇表、对象存储、规范化哈希 |
| `manorem-ir` | 已实现 | Visual IR：模型、JSON Schema 导出、三层校验、符号化时间求解 |
| `manorem-skills` | 已实现 | 领域词汇包（额外的对象类型、操作、约束） |
| `manorem-compiler` | 已实现 | IR → `RenderPlan`：归一化、布局求解、时间、相机、自动修复 |
| `manorem-renderer` | 已实现 | 沙箱化的 Manim worker（外加一个 stub），逐 scene 产出无声视频 |
| `manorem-compositor` | 已实现 | scene 拼接、转场、音频时间线、SRT/VTT 字幕 |
| `manorem-ai` | 已实现 | 提供方（Gemini / 录制的 cassette / stub）、规划 agent、有上限的修复 |
| `manorem-cli` | 已实现 | `manorem` 命令入口：`build`、`validate`、`compile`、`render`、`schema` |

对边界诚实以告：里程碑 1 的渲染结果**不做视觉质量评估**——`manorem build` 报告的是
`quality=None`，从不会说“看起来不错”，视觉 QA 阶段（`VQA6xx`）已在设计中但尚未实现。溯源
校验只能证明被引用的 URL 确实被抓取过，**并不能**证明来源支持某个论断。没有 TTS：旁白时间
是由每分钟词数模型估算出来的，所以视频是无声但有节奏、并配有同步字幕的。
`examples/scratch/scene.py` 是一个手写的 Manim 文件，仅作参考，不属于流水线。

## 整体结构

```
idea ──► story plan ──► visual plan ──► Visual IR ──► validate ──► compile ──► render ──► composite ──► video
                                            ▲            │
                                            └── repair ◄─┘   (有上限，由诊断驱动)
```

有两条性质把整个设计撑在一起。

**IR 是唯一的事实来源。** 它是语义化的：一个 `flow` cue 表示“展示数据从 A 移动到 B”，
而不是 `MoveAlongPath`。位置是*意图*（`auto`、命名 slot、锚定到另一个对象），不是坐标。
时间是*符号化*的（“当讲到卫星的那段旁白开始时”），不是秒数。所有机械性的东西都在下游
推导出来，所以同一份 IR 只要改一个字段就能重新适配 16:9、9:16 和 1:1。

**失败是结构化的，不是文本。** 每个子系统都产出同一个 `Diagnostic` 类型，用 RFC 6901
JSON Pointer 定位，带命名空间的错误码。修复循环之所以可行就在于此：它消费的是错误码和
指针，不是散文，而且有上限——绝不是无休止的重试。

## 目录布局

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
  support/                       测试套件共用的 IR / AI builder 与诊断断言
  unit/                          各包分别：core, ir, skills, compiler, renderer, compositor, ai, cli
  integration/                   手写的 GPS 示例，端到端
examples/gps/                    参考用的 Visual IR：九个 scene，外加一个引用损坏的 fixture
examples/scratch/                原始 Manim 参考文件，不参与 lint
```

故意不设根发行包：所有代码都放在 `packages/*` 里，这样沙箱化的渲染 worker 就能只安装
引擎，而不必把 API 或服务依赖一起拖进来。跨包边界的相对导入被 lint 禁止，因此依赖图保持
无环且可读——`manorem_core` 对 Manim、LLM 提供方和 IR 一无所知。

## Visual IR

一个 `Project` 装着若干 `Episode`，`Episode` 又装着若干 `Scene`。scene 是编写、生成、
渲染、缓存和修复的基本单位：它自成一体，不引用自身之外的任何东西——正因如此，逐 scene 的
AI 生成才可行（结构化输出的嵌套深度限制排除了整个 project 一次生成），修复也才是局部的：
修好 scene 4 的补丁动不了 scene 7。

一个 scene 内部有：

- **objects** —— 一组封闭的语义类型（`text`、`math`、`chart`、`globe`、`network` 等），
  每种都有自己的类型化 props 模型，于是“没有 series 的 chart”是 schema 错误，而不是
  renderer 崩溃
- **placement** —— `auto`（交给布局引擎决定）、`slot`、`anchor`（相对另一个对象），
  或者作为逃生口的显式 `stage` 坐标
- **layout** —— 声明出来的意图（`grid`、`radial`、`tree`、`split` 等），稍后再求解
- **relationships** —— 类型化的边，供布局求解器和 skill 约束使用，有时还会变成几何
  （`points_to` 会变成一支箭头）
- **narration** —— 带角色的片段（`hook`、`revelation`、`payoff` 等）；时间是推导出来的，
  从不手写
- **timeline** —— `Cue`：一个语义操作、它的目标、何时开始、持续多久，以及它*为什么*存在
- **camera** —— 一个初始位姿加上约束；相机*运动*本身就是普通的 cue，因此可以排序，也可以
  按时间锚定到画面上

位置都活在 **stage space** 里：两个轴都是 `[-1, 1]`，其中单位正方形是在任何画面比例下都
可见的安全区。在把 stage space 映射为 Manim 单位的那个编译器 pass 之前，任何地方都不会
出现世界坐标或 16:9 常量。

### 编写一个 scene

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
project.content_hash()          # '5446673f6e6d...' —— 相同的 IR 永远得到相同的哈希
```

这里没有任何一处说明标题放在哪里、1.4 秒何时到达，或者哪个 Manim 类负责画一个点。所有
模型都是冻结（`frozen`）的，因此编译器的每个 pass 都产出一份新文档，而不是就地改掉收到
的那一份。

### 传输格式

模型*就是* schema。`manorem_ir.schema` 导出 `Project` 和 `Scene` 的 JSON Schema，
为它计算摘要以检测漂移，并且是 TypeScript 侧 IR 类型、以及发给模型的结构化输出请求的
既定来源。两套手工维护的类型系统一定会走偏；由一套生成另一套则不会。

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

cue 的参数被限制为扁平的 JSON 标量——这是一条结构性的安全边界，而不是流程上的约定。参数
不能是嵌套结构，也不能是表达式，所以没有任何东西能把“行为”偷偷带到 renderer 那一侧。
需要更丰富配置的 skill，应当改为声明一个新的对象类型。

## 校验

三层，每一层都在缺陷真正可检测的层级上报告：

- **T1 结构层** —— 文档的形状。Pydantic 负责类型、取值范围和判别字段；这一层补上 schema
  表达不了的东西：重复的 id、空 scene、在目标帧率下量化后变成零帧的时长（同一份 IR 在
  60fps 下没问题，在 15fps 下就退化了）。
- **T2 引用 / 语义层** —— 文档究竟*有没有*含义。每个引用都能解析，每个操作签名都被满足，
  timeline 无环，没有东西在被显示之前就被使用。
- **T3 节奏与几何层** —— 形式正确但值得怀疑：冷场、舞台过挤、对象重叠或跑出舞台、旁白
  超出 scene 的长度。默认是警告，可按策略提升为错误。

三层都从 IR 和求解后的 plan 计算得出，从不看像素。它们确立的是一份 plan *形式正确*，这和
*好看*是两种不同的断言——观感判断属于 Visual QA 阶段及其 `VQA6xx` 错误码。

一条发现会给出错误码、严重级别，以及指向出问题文档的指针。以上面那个 scene 为例，若
`pulse` cue 的目标被误写成 `"phones"`：

```python
>>> for d in validate_scene(broken):
...     print(d)
error: IR201_UNKNOWN_OBJECT_REF [intro] at /timeline/2/targets/0: cue 'pulse' targets unknown object 'phones'
```

错误码按抛出它的阶段划分命名空间：

| 区段 | 阶段 |
| --- | --- |
| `IR1xx` | 结构 |
| `IR2xx` | 引用 / 语义 |
| `IR3xx` | 节奏与几何 lint |
| `CMP4xx` | 编译 |
| `RND5xx` | 渲染 |
| `VQA6xx` | 视觉质量（保留） |
| `MUX7xx` | 合成拼接 |
| `RES8xx` | 研究溯源 |

每个 `IR2xx` 错误码都在 `SEMANTIC_ERROR_CODES` 里，确定性自动修复被禁止碰这一集合——遇到
它就升级给有上限的修复 agent。悄悄“修好”一个悬空引用，等于丢掉作者的意图，还把规划器真正
的缺陷藏在一段看起来说得过去的视频后面。`Diagnostic.autofixable` 是从这一集合推导出来的，
而不是存下来的，所以构造诊断的人无法把语义错误重新标成无害。

时间求解放在 `manorem_ir.resolve` 而不是编译器里，因为有两个消费者都需要它，而且它们不能
各说各话：T2/T3 校验器，以及把同一批数字量化成帧的那个编译器 pass。求解是迭代到不动点，
而不是拓扑排序，所以一条部分损坏的 timeline 仍然能为形式正确的那些 cue 给出有用的时间
——这让诊断保持具体，而不是塌缩成一句“timeline 坏了”。

## 快速开始

需要 Python ≥ 3.13（仓库固定为 3.14）和 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --all-packages
```

```bash
make test
```

配置由环境变量驱动，前缀是 `MANOREM_`；把 `.env.example` 复制成 `.env` 再改。默认值是按
离线可用来选的：LLM 提供方默认 `cassette`（回放录制好的响应，不需要 API key），渲染质量
默认 `draft`，修复循环最多 2 次尝试。

## 使用命令行

`manorem` 是围绕同一条流水线的五个动词。`validate` 和 `compile` 作用于一个 Visual IR
项目，`render` 作用于编译好的 `RenderPlan`，`schema` 导出 JSON Schema，而 `build` 会离线
跑完从想法到视频的整条流水线。

```bash
manorem validate examples/gps/ir.json
manorem compile examples/gps/ir.json --aspect 16:9 -o plan.json
manorem render plan.json --quality draft -o gps.mp4
manorem build "How GPS determines your location." --aspect 16:9 -o out/
```

`build` 会把每一个中间产物——`brief.json`、`outline.json`、`script.json`、
`plan/plan_*.json`、`ir.json`、`renderplan.json`——都写在最终的 `gps.mp4` 及其 `.srt` /
`.vtt` 附属字幕旁边，因此每个阶段都可检视且内容寻址。`render` 接受 `--engine stub`，可在你
想跑通流水线又不调用 Manim 时，产出纯色帧。

一份语义损坏的 IR 会大声失败、什么也不渲染——这正是整个设计所依赖的护栏：

```bash
manorem validate examples/gps/ir_broken_ref.json   # exits 1 with an IR2xx error, no video
```

## 开发

`make` 不带目标会列出全部。下面每一项在 CI 里同样会跑：

| 目标 | 作用 |
| --- | --- |
| `make install` | 同步 workspace 全部包和开发依赖 |
| `make fmt` | 应用格式化与 import 排序 |
| `make lint` | 检查格式和 lint 规则，不写文件 |
| `make typecheck` | 对包和测试执行 `mypy --strict` |
| `make test` | 快速测试——排除真实渲染和任何需要有效 API key 的用例 |
| `make test-slow` | 基准渲染测试（真跑 Manim，耗时数分钟） |
| `make check` | lint + typecheck + test |

下面这些测试约定是承重的，不是风格问题：

- **`tests/support/ir_builders.valid_scene()` 必须在每一层都零诊断通过。** 如果新加的
  检查在它上面触发了，那是检查错了——不是 fixture 错了。一个会对普通的、形式正确的 IR
  报警的校验器比没用更糟，因为修复循环会把有限的尝试次数浪费在重写本来正确的 IR 上。
- **断言错误码和指针，绝不断言文案。** 文案是给人看的，可以随意改写；错误码和 JSON
  Pointer 才是修复 agent 和检查器依赖的机器契约。
- **一个缺陷只产出一条发现。** `tests/support/diag.only` 会在同一个检查触发两次时失败，
  因为重复的发现会灌满修复循环。
- 测试要精确声明自己所在的层（`error_codes` / `warning_codes`），这样一个语义测试就不会
  被顺带冒出来的节奏警告绑住。

## 设计原则

这个仓库里大部分不那么显然的选择，都来自少数几个立场：

- **封闭词汇表。** 对象类型、操作、布局和缓动函数全部是 enum。模型只能从编译器保证能理解
  的菜单里挑；把菜单加宽是一个刻意的动作——加成员、加编译器里的处理、加它的测试。
- **表驱动校验。** 操作自己声明签名（`CORE_OPERATIONS`），所以新增一个操作等于新增一条
  声明，而不是再多一个分支。生成提示词也由同一批声明构建，因此模型看到的菜单和校验器的
  规则不可能各自漂移。
- **处处内容寻址。** 产物以其规范化 JSON 的 sha256 作为键，由此换来去重、廉价的版本管理，
  以及逐字节精确的确定性检查。带随机成分的布局求解器出于同样的理由使用固定种子。
- **拒绝，而不是清洗。** 格式错误的存储 key 和非法 id 会直接抛异常，而不是被悄悄改写——
  写出这种值的调用方有 bug，默默替它修好只是把 bug 藏起来。`slugify` 只用于机器生成的
  名字。
- **持久化的 schema 都带版本号。** 有了 `Project.ir_version`，更早存下来的 IR 会被识别
  并迁移，而不是被解析错。
