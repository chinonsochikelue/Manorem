"""The staged orchestrator: an idea in, a captioned video out.

The pipeline is written as an explicit chain of stages, each a total function
from one typed artifact to the next: research -> story -> script -> pacing ->
per-beat visual plan -> per-beat scene -> assembled project -> compiled plan ->
render -> visual-QA seam -> composite. Every stage artifact is persisted
content-addressed by the sha256 of its canonical JSON, which is what lets a later
edit re-run only the stages whose inputs actually changed.

Three guardrails are load-bearing here and are enforced by structure, not by
discipline:

* **Provenance before story.** A brief whose citations were not all retrieved is
  rejected before a single beat is planned -- a fabricated source never becomes
  narration.
* **Invalid IR never reaches the renderer.** Compilation runs the bounded repair
  loop; if semantic errors survive it, the pipeline raises rather than rendering a
  plan that dropped a satellite.
* **Repair patches, never rewrites.** Semantic diagnostics (pre-render) and
  error-severity ``VQA6xx`` findings (post-render) are both grouped by scene and
  routed to :class:`~manorem_ai.agents.RepairAgent`, and every patch is applied
  through :func:`~manorem_ai.patch.apply_scene_patch`, which refuses a patch that
  changes which entities exist. Both loops patch the *IR* -- never the plan, never
  the pixels -- and each is capped at ``max_repair_attempts``.
"""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from manorem_ai.agents import (
    IRGeneratorAgent,
    RepairAgent,
    ResearchAgent,
    ScriptAgent,
    StoryAgent,
    VisualPlannerAgent,
)
from manorem_ai.agents.models import Script, StoryOutline, VisualPlan
from manorem_ai.pacing import PacingReport, pace_script
from manorem_ai.patch import PatchError, apply_scene_patch
from manorem_ai.provider import LLMProvider
from manorem_ai.quality import NoopVisualQA, VisualQA
from manorem_ai.research import (
    Document,
    ProvenanceValidator,
    ResearchBrief,
    ResearchProvider,
)
from manorem_ai.tts import TTSError, TTSProvider, TTSRequest, tts_cache_key, wav_duration_seconds
from manorem_compiler import CompileOptions, RenderPlan, compile_project
from manorem_compositor import CompositionResult, Compositor
from manorem_core import (
    SEMANTIC_ERROR_CODES,
    Code,
    Diagnostic,
    DiagnosticBag,
    ManoremError,
    ObjectStore,
    Settings,
    Severity,
    canonical_bytes,
    get_logger,
    get_settings,
    pointer,
    sha256_of,
    slugify,
)
from manorem_ir import Aspect, Episode, FormatSpec, Project, Scene, StyleTokens, retime_narration
from manorem_renderer import (
    VQA_ERROR_CODES,
    QualityReport,
    Renderer,
    RenderOptions,
    RenderResult,
    StubRenderer,
)
from manorem_skills import SkillRegistry, default_registry, vocabulary_prompt

__all__ = ["Pipeline", "PipelineError", "PipelineResult"]

_LOG = get_logger("manorem.ai.pipeline")


class PipelineError(ManoremError):
    """A stage produced output the pipeline refuses to carry forward.

    Raised for fabricated provenance, a beat/segment count mismatch, or semantic
    diagnostics that survived the bounded repair loop -- each a case where
    continuing would mean rendering something that misrepresents the input.
    """


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Every artifact a run produced, in stage order, plus their content digests.

    Holding the intermediate artifacts -- not just the final video -- is what makes
    the run inspectable and re-runnable: ``digests`` maps each stage to the sha256
    of its canonical JSON, so an unchanged stage is recognisable by its hash alone.
    ``composition`` is ``None`` when the render did not complete, and ``quality`` is
    ``None`` whenever the (M1) Visual QA seam declined to assess -- never conflated
    with "assessed and fine".
    """

    idea: str
    documents: tuple[Document, ...]
    brief: ResearchBrief
    outline: StoryOutline
    script: Script
    pacing: PacingReport
    plans: tuple[VisualPlan, ...]
    project: Project
    plan: RenderPlan
    diagnostics: DiagnosticBag
    render: RenderResult
    quality: QualityReport | None
    composition: CompositionResult | None
    repair_attempts: int
    digests: dict[str, str]
    #: Audio synthesis summary when a TTS provider was wired: the metadata block
    #: plus one row per synthesized segment (id, window, measured duration, asset).
    #: ``None`` when audio is disabled (``tts=None``) -- the silent pipeline, which
    #: stays byte-identical to the pre-M3 run.
    audio: dict[str, object] | None = None

    @property
    def video(self) -> Path | None:
        """The final muxed deliverable, if the render and mux both completed."""
        return self.composition.video if self.composition is not None else None


@dataclass(frozen=True, slots=True)
class _SegmentAudio:
    """One synthesized segment's workspace-relative asset key and measured length."""

    asset: str
    duration_s: float


class Pipeline:
    """Wires the agents and backends into one ``build`` from idea to video.

    Everything the run needs is injected: the LLM provider (a real Gemini client,
    or an offline cassette/stub in tests), the research source, the artifact store,
    and the render/QA/composite backends. Model ids, temperature, wpm and the
    repair cap all come from :class:`~manorem_core.Settings`, never from literals at
    a call site.
    """

    def __init__(
        self,
        provider: LLMProvider,
        research: ResearchProvider,
        *,
        store: ObjectStore,
        renderer: Renderer | None = None,
        compositor: Compositor | None = None,
        visual_qa: VisualQA | None = None,
        tts: TTSProvider | None = None,
        registry: SkillRegistry | None = None,
        settings: Settings | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self._settings = cfg
        self._research = research
        self._store = store
        self._renderer: Renderer = renderer or StubRenderer()
        self._compositor = compositor or Compositor()
        self._visual_qa: VisualQA = visual_qa or NoopVisualQA()
        self._tts = tts
        self._registry = registry or default_registry()
        self._provenance = ProvenanceValidator()

        temp = cfg.llm_temperature
        tokens = cfg.llm_max_tokens
        light = cfg.gemini_model
        heavy = cfg.gemini_model_heavy
        self._research_agent = ResearchAgent(
            provider, model=light, temperature=temp, max_tokens=tokens
        )
        self._story_agent = StoryAgent(provider, model=heavy, temperature=temp, max_tokens=tokens)
        self._script_agent = ScriptAgent(provider, model=light, temperature=temp, max_tokens=tokens)
        self._planner = VisualPlannerAgent(
            provider, model=heavy, temperature=temp, max_tokens=tokens
        )
        self._generator = IRGeneratorAgent(
            provider, model=light, temperature=temp, max_tokens=tokens
        )
        self._repair_agent = RepairAgent(provider, model=light, temperature=temp, max_tokens=tokens)

    def build(
        self,
        idea: str,
        *,
        aspect: Aspect | None = None,
        quality: str | None = None,
        workspace: Path | None = None,
    ) -> PipelineResult:
        """Run every stage for ``idea`` and return all of its artifacts."""
        digests: dict[str, str] = {}
        work = (workspace or self._settings.workspace_root).resolve()
        work.mkdir(parents=True, exist_ok=True)

        documents = self._research.retrieve(idea)
        brief = self._research_agent.run(idea, documents).value
        self._check_provenance(brief, documents)
        digests["brief"] = self._persist(brief)

        outline = self._story_agent.run(brief).value
        digests["outline"] = self._persist(outline)

        script = self._script_agent.run(outline).value
        digests["script"] = self._persist(script)
        pacing = pace_script(script.segments, wpm=self._settings.narration_wpm)

        plans, scenes = self._author_scenes(outline, script, digests)
        project = self._assemble_project(idea, outline, scenes, aspect=aspect, quality=quality)

        project, assets, audio_bag, audio_summary = self._narrate(project, work)

        options = CompileOptions()
        project, plan, bag, attempts = self._compile_with_repair(project, options)
        if bag.has_errors:
            raise PipelineError(
                "compilation left semantic errors the repair loop could not clear: "
                + "; ".join(str(d) for d in bag.errors)
            )
        bag.extend(audio_bag)

        project, plan, render, report, composition, visual_attempts = self._render_qa_repair(
            project, plan, options, work, assets
        )
        digests["ir"] = self._persist(project)
        digests["renderplan"] = self._persist(plan)
        if audio_summary is not None:
            digests["audio"] = sha256_of(audio_summary)

        return PipelineResult(
            idea=idea,
            documents=documents,
            brief=brief,
            outline=outline,
            script=script,
            pacing=pacing,
            plans=plans,
            project=project,
            plan=plan,
            diagnostics=bag,
            render=render,
            quality=report,
            composition=composition,
            repair_attempts=attempts + visual_attempts,
            digests=digests,
            audio=audio_summary,
        )

    # -- stages ---------------------------------------------------------------

    def _check_provenance(self, brief: ResearchBrief, documents: tuple[Document, ...]) -> None:
        """Reject a brief that cites a URL that was never retrieved (guardrail #2)."""
        bag = self._provenance.validate(brief, documents)
        if bag.has_errors:
            raise PipelineError(
                "brief cites sources that were not retrieved (fabricated provenance): "
                + "; ".join(str(d) for d in bag.errors)
            )

    def _author_scenes(
        self, outline: StoryOutline, script: Script, digests: dict[str, str]
    ) -> tuple[tuple[VisualPlan, ...], tuple[Scene, ...]]:
        """Plan and realize one scene per beat, pairing beats with segments by order."""
        if len(script.segments) < len(outline.beats):
            raise PipelineError(
                f"script has {len(script.segments)} segments for {len(outline.beats)} beats; "
                "each beat needs a narration segment to author its scene"
            )
        menu = vocabulary_prompt(self._registry.resolve(sorted(self._registry.ids)))
        plans: list[VisualPlan] = []
        scenes: list[Scene] = []
        for index, beat in enumerate(outline.beats):
            segment = script.segments[index]
            plan = self._planner.run(beat, segment, vocabulary=menu).value
            digests[f"plan.{index}"] = self._persist(plan)
            scoped = vocabulary_prompt(self._registry.resolve(plan.skills))
            scene = self._generator.run(plan, segment, vocabulary=scoped).value
            plans.append(plan)
            scenes.append(scene)
        return tuple(plans), tuple(scenes)

    def _assemble_project(
        self,
        idea: str,
        outline: StoryOutline,
        scenes: tuple[Scene, ...],
        *,
        aspect: Aspect | None,
        quality: str | None,
    ) -> Project:
        """Gather the authored scenes into one single-episode project."""
        fmt = FormatSpec.for_quality(
            aspect or Aspect.WIDESCREEN, quality or self._settings.render_quality.value
        )
        episode = Episode(id=slugify("episode-1"), title=outline.title, scenes=list(scenes))
        return Project(
            id=slugify(idea) or slugify("project"),
            title=outline.title,
            idea=idea,
            style=StyleTokens(),
            format=fmt,
            episodes=[episode],
            narration_wpm=self._settings.narration_wpm,
        )

    # -- narration synthesis (M3 audio timing authority) ----------------------

    def _narrate(
        self, project: Project, workspace: Path
    ) -> tuple[Project, dict[tuple[str, str], str], DiagnosticBag, dict[str, object] | None]:
        """Synthesize speech per scene and let its measured durations drive timing.

        This is the stage that makes audio the timing authority. For each scene it
        synthesizes every narration segment, measures each clip's real duration from
        its WAV header, and -- only if the *whole scene* succeeded -- rewrites that
        scene's segment windows end-to-end from those measurements via
        :func:`~manorem_ir.retime_narration`. From there ``narration_windows`` takes
        its real-timing branch and every downstream consumer (``at_narration`` cue
        anchoring, frame quantization, subtitles) reads one clock with no second
        timing system. The asset keys stay *out* of the IR: they are returned
        separately, namespaced by ``(scene_id, segment_id)``, and attached to the
        compiled plan's :class:`AudioCue`s by :meth:`_attach_audio`.

        Failure is **scene-atomic** (invariant #2): if any segment in a scene fails
        to synthesize or yields unreadable audio, that whole scene reverts to WPM
        timing (retimed with an empty map), none of its assets are recorded, and one
        ``AUD901`` is emitted. Other scenes are unaffected.

        When no TTS provider was wired (``tts is None``) this is a no-op that returns
        the project untouched with no assets and no diagnostics -- the silent
        pipeline, byte-identical to the pre-M3 run (invariant #5).
        """
        if self._tts is None:
            return project, {}, DiagnosticBag(), None

        bag = DiagnosticBag()
        assets: dict[tuple[str, str], str] = {}
        rows: list[dict[str, object]] = []
        changed: dict[str, Scene] = {}
        audio_dir = workspace / "audio"

        for ep_index, episode in enumerate(project.episodes):
            for sc_index, scene in enumerate(episode.scenes):
                try:
                    synthesized = self._synthesize_scene(scene, audio_dir)
                except TTSError as exc:
                    bag.warn(
                        Code.AUD901_TTS_PROVIDER_FAILED,
                        f"speech synthesis failed for scene {scene.id!r}; "
                        f"falling back to WPM timing: {exc}",
                        scene_id=scene.id,
                        pointer=pointer("episodes", ep_index, "scenes", sc_index),
                    )
                    changed[scene.id] = retime_narration(scene, {})
                    continue

                durations = {seg_id: audio.duration_s for seg_id, audio in synthesized.items()}
                changed[scene.id] = retime_narration(scene, durations)
                for segment in scene.narration:
                    audio = synthesized[segment.id]
                    assets[(scene.id, segment.id)] = audio.asset
                    rows.append(
                        {
                            "scene_id": scene.id,
                            "segment_id": segment.id,
                            "role": segment.role.value,
                            "text": segment.text,
                            "duration_s": audio.duration_s,
                            "asset": audio.asset,
                        }
                    )

        retimed = self._replace_scenes(project, changed) if changed else project
        summary = self._write_audio_sidecars(retimed, rows, audio_dir)
        return retimed, assets, bag, summary

    def _synthesize_scene(self, scene: Scene, audio_dir: Path) -> dict[str, _SegmentAudio]:
        """Synthesize every segment of one scene; raise :class:`TTSError` on any failure.

        Scene-atomic by construction: this returns a complete per-segment map or
        raises, so the caller never has to reason about a partially voiced scene.
        Each clip is content-addressed by its provider-neutral request digest and
        cached in the object store, so an unchanged line is synthesized once and
        reused across runs; the bytes are also materialized under
        ``workspace/audio/<digest>.wav`` for the compositor to mix.
        """
        assert self._tts is not None  # guaranteed by _narrate
        cfg = self._settings
        audio_dir.mkdir(parents=True, exist_ok=True)
        result: dict[str, _SegmentAudio] = {}
        for segment in scene.narration:
            request = TTSRequest(
                text=segment.text,
                voice=cfg.tts_voice,
                language=cfg.tts_language,
                speed=cfg.tts_speed,
                sample_rate=cfg.tts_sample_rate,
            )
            digest = tts_cache_key(request)
            key = f"audio/{digest}.wav"
            if self._store.exists(key):
                data = self._store.get_bytes(key)
            else:
                data = self._tts.synthesize(request).data
                self._store.put_bytes(key, data)
            local = audio_dir / f"{digest}.wav"
            local.write_bytes(data)
            result[segment.id] = _SegmentAudio(
                asset=f"audio/{digest}.wav",
                duration_s=wav_duration_seconds(data),
            )
        return result

    def _write_audio_sidecars(
        self, project: Project, rows: list[dict[str, object]], audio_dir: Path
    ) -> dict[str, object]:
        """Persist ``audio/segments.json`` + ``audio/metadata.json``; return the summary.

        The sidecars make a run's audio inspectable without decoding a video: one row
        per synthesized segment (its measured window, duration and asset) plus a
        metadata block naming the voice settings and provider. The returned summary
        is also what :class:`PipelineResult.audio` carries and what the ``audio``
        digest is taken over.
        """
        audio_dir.mkdir(parents=True, exist_ok=True)
        windows: dict[str, tuple[float | None, float | None]] = {}
        for scene in project.scenes:
            for segment in scene.narration:
                windows[segment.id] = (segment.start, segment.end)
        segments = [
            {
                **row,
                "start": windows.get(str(row["segment_id"]), (None, None))[0],
                "end": windows.get(str(row["segment_id"]), (None, None))[1],
            }
            for row in rows
        ]
        cfg = self._settings
        metadata: dict[str, object] = {
            "provider": self._tts.name if self._tts is not None else None,
            "voice": cfg.tts_voice,
            "language": cfg.tts_language,
            "speed": cfg.tts_speed,
            "sample_rate": cfg.tts_sample_rate,
            "format": "wav",
            "segment_count": len(segments),
        }
        (audio_dir / "segments.json").write_text(
            json.dumps(segments, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (audio_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return {"metadata": metadata, "segments": segments}

    def _attach_audio(self, plan: RenderPlan, assets: Mapping[tuple[str, str], str]) -> RenderPlan:
        """Set each :class:`AudioCue`'s ``asset`` from the scene-namespaced map.

        Audio keys never live in the IR; they are bound to the *compiled plan* here,
        matching each cue by its owning ``(scene_id, segment_id)`` (invariant #1 --
        ``segment_id`` is unique only within a scene, so the bare id is never the
        key). Flipping ``asset`` from ``None`` is exactly what tips
        :class:`~manorem_ir.AudioTimeline` out of its silent state so the compositor
        mixes. A no-op for an empty map, which keeps the silent plan byte-identical.
        """
        if not assets:
            return plan
        scenes = []
        for scene in plan.scenes:
            cues = tuple(
                cue.model_copy(update={"asset": assets[(scene.id, cue.segment_id)]})
                if (scene.id, cue.segment_id) in assets
                else cue
                for cue in scene.audio_cues
            )
            scenes.append(scene.model_copy(update={"audio_cues": cues}))
        return plan.model_copy(update={"scenes": tuple(scenes)})

    # -- compile with bounded repair ------------------------------------------

    def _compile_with_repair(
        self, project: Project, options: CompileOptions
    ) -> tuple[Project, RenderPlan, DiagnosticBag, int]:
        """Compile, and while semantic errors remain, patch and recompile (<= cap).

        Only diagnostics in :data:`~manorem_core.SEMANTIC_ERROR_CODES` are routed to
        the repair agent; a non-semantic error (a compiler fault) is not something a
        scene patch can fix, so the loop stops and the caller raises. The loop also
        stops early if an attempt changes nothing -- no scene could be patched.
        """
        attempts = 0
        current = project
        plan, bag = compile_project(current, options)
        while bag.has_errors and attempts < self._settings.max_repair_attempts:
            semantic = [d for d in bag.errors if d.code in SEMANTIC_ERROR_CODES]
            if not semantic:
                break
            attempts += 1
            repaired = self._repair_scenes(current, semantic)
            if repaired is current:
                break
            current = repaired
            plan, bag = compile_project(current, options)
        return current, plan, bag, attempts

    def _repair_scenes(self, project: Project, diagnostics: Sequence[Diagnostic]) -> Project:
        """Patch each scene that owns a semantic diagnostic; return the new project.

        Diagnostics are grouped by ``scene_id`` so each scene is repaired against its
        own errors and its own skill vocabulary. Every patch goes through
        :func:`apply_scene_patch`, which rejects any patch that adds or drops an
        entity; a rejected or unlocatable scene is left untouched (it stays an error)
        rather than forced.
        """
        by_scene: dict[str, list[Diagnostic]] = defaultdict(list)
        for diagnostic in diagnostics:
            if diagnostic.scene_id is not None:
                by_scene[diagnostic.scene_id].append(diagnostic)

        changed: dict[str, Scene] = {}
        for scene_id, scene_diags in by_scene.items():
            located = project.locate_scene(scene_id)
            if located is None:
                continue
            scene = located[1]
            vocabulary = vocabulary_prompt(self._registry.resolve(scene.skills))
            patch = self._repair_agent.run(scene, scene_diags, vocabulary=vocabulary).value
            try:
                changed[scene_id] = apply_scene_patch(scene, patch)
            except PatchError as exc:
                _LOG.warning("repair.rejected", scene_id=scene_id, reason=str(exc))
                continue
            _LOG.info("repair.applied", scene_id=scene_id, operations=len(patch.operations))

        if not changed:
            return project
        return self._replace_scenes(project, changed)

    @staticmethod
    def _replace_scenes(project: Project, changed: dict[str, Scene]) -> Project:
        """Swap the named scenes into their episodes, leaving the rest untouched."""
        episodes = [
            episode.model_copy(
                update={"scenes": [changed.get(scene.id, scene) for scene in episode.scenes]}
            )
            for episode in project.episodes
        ]
        return project.model_copy(update={"episodes": episodes})

    # -- render, QA seam, composite -------------------------------------------

    def _render_qa_repair(
        self,
        project: Project,
        plan: RenderPlan,
        options: CompileOptions,
        workspace: Path,
        assets: Mapping[tuple[str, str], str],
    ) -> tuple[
        Project, RenderPlan, RenderResult, QualityReport | None, CompositionResult | None, int
    ]:
        """Render, assess, and while error-severity VQA findings remain, repair and rerun.

        This is the *post-render* repair loop, and it is deliberately separate from
        :meth:`_compile_with_repair`. A visual defect -- text off-stage, two mobjects
        colliding, copy too small to read -- is not a semantic error and never surfaces
        pre-render, so VQA6xx codes are absent from
        :data:`~manorem_core.SEMANTIC_ERROR_CODES`. Here we select exactly the
        error-severity VQA findings (:data:`~manorem_renderer.VQA_ERROR_CODES`), group
        them by scene, and patch the **IR** through the same :class:`RepairAgent` and
        :func:`apply_scene_patch` the semantic loop uses -- never the plan and never the
        pixels, because the IR is the source of truth. Each repaired project is
        recompiled (clearing any semantic error the patch introduced) and rerendered,
        then reassessed. Bounded by ``max_repair_attempts``; the loop also stops early
        when a round patches nothing.

        Under M1's :class:`~manorem_ai.quality.NoopVisualQA` the report is ``None`` and
        the loop never runs -- the render is *not assessed*, and nothing gates on it.
        """
        render, report, composition = self._render_and_composite(plan, workspace, assets)
        attempts = 0
        while (
            report is not None
            and attempts < self._settings.max_repair_attempts
            and any(f.severity is Severity.ERROR for f in report.findings)
        ):
            visual_errors = [
                f
                for f in report.findings
                if f.severity is Severity.ERROR and f.code in VQA_ERROR_CODES
            ]
            if not visual_errors:
                break
            attempts += 1
            repaired = self._repair_scenes(project, visual_errors)
            if repaired is project:
                break
            project = repaired
            project, plan, bag, _ = self._compile_with_repair(project, options)
            if bag.has_errors:
                raise PipelineError(
                    "repairing a visual defect reintroduced semantic errors the repair "
                    "loop could not clear: " + "; ".join(str(d) for d in bag.errors)
                )
            _LOG.info("visual_repair.applied", attempt=attempts, findings=len(visual_errors))
            render, report, composition = self._render_and_composite(plan, workspace, assets)
        return project, plan, render, report, composition, attempts

    def _render_and_composite(
        self, plan: RenderPlan, workspace: Path, assets: Mapping[tuple[str, str], str]
    ) -> tuple[RenderResult, QualityReport | None, CompositionResult | None]:
        """Render the plan, run the (non-blocking) QA seam, then mux to a deliverable.

        ``assess`` returns ``None`` under M1's :class:`~manorem_ai.quality.NoopVisualQA`
        -- *not assessed*, never *assessed and fine* -- and nothing here gates on it.
        A render that did not complete short-circuits: there is nothing to composite,
        and the missing video is reported honestly rather than papered over.

        Audio asset keys are bound to the plan here, just before compositing, via
        :meth:`_attach_audio` -- so they are re-applied to every recompiled plan the
        VQA repair loop produces (scene/segment ids survive geometry repair), and the
        persisted/returned plan stays asset-free. A no-op when ``assets`` is empty.
        """
        plan = self._attach_audio(plan, assets)
        opts = RenderOptions(
            quality=self._settings.render_quality.value,
            timeout_s=float(self._settings.render_timeout_s),
            sample_rate_hz=self._settings.frame_sample_hz,
        )
        render = self._renderer.render(plan, opts)
        report = self._visual_qa.assess(plan, render)
        if not render.ok or render.video is None:
            _LOG.warning("render.incomplete", status=render.status.value)
            return render, report, None

        scene_video = workspace / f"scene{render.video.suffix}"
        shutil.copy2(render.video, scene_video)
        composition = self._compositor.compose(plan, (scene_video,), workspace)
        return render, report, composition

    def _persist(self, value: BaseModel) -> str:
        """Store a stage artifact content-addressed by the sha256 of its canonical JSON."""
        digest = sha256_of(value)
        self._store.put_bytes(f"artifacts/{digest}.json", canonical_bytes(value))
        return digest
