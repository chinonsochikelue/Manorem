"""The real backend: hand a finished plan to Manim, in a subprocess, and wait.

``ManimRenderer`` never imports Manim itself -- that keeps this process (and the
fast test suite) free of a heavy, LaTeX-shaped dependency, and it is what makes
the subprocess a genuine isolation boundary rather than a formality. It writes the
plan to a job workspace, points the fixed :mod:`~manorem_renderer.manim.plan_scene`
interpreter at it through ``MANOREM_PLAN_PATH``, and invokes ``python -m manim``
with an argv list (never a shell string, §26). The subprocess gets a wall-clock
timeout; on Windows that is the enforceable limit, since the POSIX ``resource``
caps are unavailable, so memory/CPU ceilings are a Linux-container concern (the
worker image) rather than something this launcher can promise here.

Rendering completing is not rendering being *good*: this returns
``quality=None``, and the manifest plus extracted frame samples are the inputs a
future QA stage will read.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from manorem_compiler import RenderPlan
from manorem_core import Code, Diagnostic, Severity
from manorem_renderer.manifest import build_manifest
from manorem_renderer.results import (
    Capability,
    RenderManifest,
    RenderOptions,
    RenderResult,
    RenderStatus,
)

__all__ = ["ManimGLRenderer", "ManimRenderer", "WebGLRenderer"]

#: Must match ``plan_scene.PLAN_ENV``. Duplicated rather than imported because
#: importing that module would pull Manim into this process and defeat isolation.
_PLAN_ENV = "MANOREM_PLAN_PATH"

_SCENE_FILE = Path(__file__).parent / "manim" / "plan_scene.py"
_SCENE_CLASS = "PlanScene"

_CAPABILITIES = frozenset(
    {
        Capability.RASTER_VIDEO,
        Capability.FRAME_SAMPLES,
        Capability.SCENE_MANIFEST,
        Capability.CAMERA_MOVES,
    }
)


class ManimRenderer:
    """Interprets a :class:`RenderPlan` by driving Manim in an isolated subprocess."""

    name = "manim"
    capabilities = _CAPABILITIES

    def render(self, plan: RenderPlan, opts: RenderOptions) -> RenderResult:
        start = time.monotonic()
        manifest = build_manifest(plan, sample_rate_hz=opts.sample_rate_hz)
        workspace = Path(tempfile.mkdtemp(prefix="manorem-manim-"))
        plan_path = workspace / "plan.json"
        plan_path.write_text(plan.model_dump_json(), encoding="utf-8")

        status, video, diagnostics = self._invoke(plan, plan_path, workspace, opts)
        samples = (
            self._extract_samples(plan, manifest, video, workspace)
            if status is RenderStatus.OK and video is not None
            else ()
        )
        return RenderResult(
            status=status,
            video=video,
            frame_samples=samples,
            manifest=manifest,
            quality=None,
            diagnostics=diagnostics,
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    def _invoke(
        self, plan: RenderPlan, plan_path: Path, workspace: Path, opts: RenderOptions
    ) -> tuple[RenderStatus, Path | None, tuple[Diagnostic, ...]]:
        argv = [
            sys.executable,
            "-m",
            "manim",
            "render",
            str(_SCENE_FILE),
            _SCENE_CLASS,
            "-r",
            f"{plan.format.width},{plan.format.height}",
            "--fps",
            str(plan.fps),
            "--media_dir",
            str(workspace),
            "--format",
            "mp4",
            "--disable_caching",
        ]
        env = {**os.environ, _PLAN_ENV: str(plan_path)}
        try:
            completed = subprocess.run(
                argv, capture_output=True, timeout=opts.timeout_s, check=False, env=env
            )
        except subprocess.TimeoutExpired:
            timed_out = Diagnostic(
                code=Code.RND502_RENDER_TIMEOUT,
                severity=Severity.ERROR,
                message=f"manim render exceeded its {opts.timeout_s:.0f}s budget",
            )
            return RenderStatus.TIMEOUT, None, (timed_out,)

        if completed.returncode != 0:
            tail = completed.stderr.decode("utf-8", "replace")[-2000:]
            failed = Diagnostic(
                code=Code.RND501_RENDERER_FAILED,
                severity=Severity.ERROR,
                message=f"manim render exited {completed.returncode}",
                hint=tail,
            )
            return RenderStatus.FAILED, None, (failed,)

        video = next(iter(sorted(workspace.rglob(f"{_SCENE_CLASS}.mp4"))), None)
        if video is None:
            missing = Diagnostic(
                code=Code.RND501_RENDERER_FAILED,
                severity=Severity.ERROR,
                message="manim reported success but produced no video file",
            )
            return RenderStatus.FAILED, None, (missing,)
        return RenderStatus.OK, video, ()

    def _extract_samples(
        self, plan: RenderPlan, manifest: RenderManifest, video: Path, workspace: Path
    ) -> tuple[Path, ...]:
        """One PNG per sampled frame, pulled from the concatenated video by time.

        The plan renders every scene back to back into one file, so a scene-local
        sample frame maps to a global timestamp by summing the durations of the
        scenes before it. Missing FFmpeg means no samples -- the manifest still
        stands on its own.
        """
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            return ()
        paths: list[Path] = []
        offset = 0
        for scene, scene_manifest in zip(plan.scenes, manifest.scenes, strict=True):
            for frame in scene_manifest.frames:
                timestamp = (offset + frame.frame) / plan.fps
                path = workspace / f"{scene_manifest.scene_id}_{frame.frame:06d}.png"
                argv = [
                    ffmpeg,
                    "-y",
                    "-ss",
                    f"{timestamp:.6f}",
                    "-i",
                    str(video),
                    "-frames:v",
                    "1",
                    str(path),
                ]
                subprocess.run(argv, capture_output=True, timeout=60, check=False)
                if path.exists():
                    paths.append(path)
            offset += scene.duration_frames
        return tuple(paths)


class _UnimplementedRenderer:
    """A declared-but-unbuilt backend: advertises its capabilities, refuses to run.

    Lets a caller reason about what a future backend *will* do (so capability
    gating is real today) without pretending it renders. Calling ``render``
    raises rather than returning a misleading result.
    """

    name = "unimplemented"
    capabilities: frozenset[Capability] = frozenset()

    def render(self, plan: RenderPlan, opts: RenderOptions) -> RenderResult:
        del plan, opts
        raise NotImplementedError(f"{self.name} renderer is not implemented in M1")


class ManimGLRenderer(_UnimplementedRenderer):
    """OpenGL Manim backend -- declared for capability gating, unbuilt in M1."""

    name = "manimgl"
    capabilities = frozenset(
        {Capability.RASTER_VIDEO, Capability.CAMERA_MOVES, Capability.FRAME_SAMPLES}
    )


class WebGLRenderer(_UnimplementedRenderer):
    """Browser/WebGL backend -- declared for capability gating, unbuilt in M1."""

    name = "webgl"
    capabilities = frozenset({Capability.RASTER_VIDEO, Capability.TRANSPARENT_BACKGROUND})
