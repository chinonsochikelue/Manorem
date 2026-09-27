"""A renderer that makes the pipeline runnable without Manim or LaTeX.

Solid-colour frames from FFmpeg stand in for real animation, so an integration
test can exercise the whole ``idea -> MP4`` path in about a second instead of a
minute, and CI never needs a TeX install to stay green. Crucially the stub emits
the *same* manifest and frame samples every backend does -- both are computed
from the plan, not the pixels, so they are byte-identical to Manim's -- which
means the QA seam is exercised even though the frames themselves are blank.

If FFmpeg is absent the stub still produces its manifest and frame samples and
reports ``FAILED`` with an ``RND501`` diagnostic rather than raising: the plan may
be perfectly good and only the environment lacking.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image

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

__all__ = ["StubRenderer"]

_CAPABILITIES = frozenset(
    {Capability.RASTER_VIDEO, Capability.FRAME_SAMPLES, Capability.SCENE_MANIFEST}
)


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    digits = color.lstrip("#")
    return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)


class StubRenderer:
    """Solid-colour stand-in backend. Fast, offline, deterministic manifest."""

    name = "stub"
    capabilities = _CAPABILITIES

    def render(self, plan: RenderPlan, opts: RenderOptions) -> RenderResult:
        start = time.monotonic()
        manifest = build_manifest(plan, sample_rate_hz=opts.sample_rate_hz)
        workspace = Path(tempfile.mkdtemp(prefix="manorem-stub-"))
        samples = self._write_samples(plan, manifest, workspace)
        video, diagnostics, status = self._write_video(plan, workspace)
        return RenderResult(
            status=status,
            video=video,
            frame_samples=samples,
            manifest=manifest,
            quality=None,
            diagnostics=diagnostics,
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    def _write_samples(
        self, plan: RenderPlan, manifest: RenderManifest, workspace: Path
    ) -> tuple[Path, ...]:
        width, height = plan.format.width, plan.format.height
        paths: list[Path] = []
        for scene_manifest in manifest.scenes:
            scene = plan.scene(scene_manifest.scene_id)
            background = scene.background if scene is not None else plan.style.background
            rgb = _hex_to_rgb(background)
            for frame in scene_manifest.frames:
                path = workspace / f"{scene_manifest.scene_id}_{frame.frame:06d}.png"
                Image.new("RGB", (width, height), rgb).save(path)
                paths.append(path)
        return tuple(paths)

    def _write_video(
        self, plan: RenderPlan, workspace: Path
    ) -> tuple[Path | None, tuple[Diagnostic, ...], RenderStatus]:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            failed = Diagnostic(
                code=Code.RND501_RENDERER_FAILED,
                severity=Severity.ERROR,
                message="ffmpeg not found on PATH; the stub cannot emit a video",
            )
            return None, (failed,), RenderStatus.FAILED

        video = workspace / "render.mp4"
        seconds = plan.total_frames / plan.fps
        color = "0x" + plan.style.background.lstrip("#")
        source = f"color=c={color}:s={plan.format.width}x{plan.format.height}:r={plan.fps}"
        argv = [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            source,
            "-t",
            f"{seconds:.6f}",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ]
        completed = subprocess.run(argv, capture_output=True, timeout=120, check=False)
        if completed.returncode != 0 or not video.exists():
            failed = Diagnostic(
                code=Code.RND501_RENDERER_FAILED,
                severity=Severity.ERROR,
                message=f"ffmpeg exited {completed.returncode} while writing the stub video",
            )
            return None, (failed,), RenderStatus.FAILED
        return video, (), RenderStatus.OK
