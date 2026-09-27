"""The typed FFmpeg argv builder -- the §26 boundary for the post step.

FFmpeg is a subprocess, and the one rule that makes it safe is the same one the
renderer follows: **build an argument vector, never a shell string.** A shell
string invites quoting bugs and, with any interpolated path, command injection; a
list handed to :func:`subprocess.run` is passed to the OS verbatim, argument by
argument, with no shell to reinterpret it.

Every path this command references must live inside the job workspace. That is
not decoration: the compositor concatenates renderer output and writes subtitles,
and a path that escaped the workspace would let a crafted plan read or overwrite
something it should not. So :class:`FFmpegCommand` refuses a path outside its
workspace outright -- :class:`~manorem_core.UnsafePathError`, never a silent
clamp -- exactly as :func:`~manorem_core.validate_key` does for storage keys.

Paths are emitted **relative to the workspace**, and the compositor runs FFmpeg
with the workspace as its working directory. That keeps a rendered ``argv``
deterministic (no absolute temp path leaks into a golden), and it sidesteps the
``subtitles`` filter's habit of treating a Windows drive letter's colon as an
option separator.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from manorem_core import UnsafePathError

__all__ = ["FFmpegCommand", "FFmpegInput", "workspace_relative"]


def workspace_relative(workspace: Path, path: Path) -> str:
    """Path as a workspace-relative POSIX string, or refuse it.

    Resolved before the check so ``..`` cannot smuggle an escape past a lexical
    comparison, mirroring :class:`~manorem_core.LocalFSStore`. Non-existent paths
    resolve fine -- the output file does not exist yet when the command is built.
    """
    root = workspace.expanduser().resolve()
    candidate = (root / path).resolve() if not path.is_absolute() else path.resolve()
    if not candidate.is_relative_to(root):
        raise UnsafePathError(f"ffmpeg path escapes the job workspace: {path!s}")
    return candidate.relative_to(root).as_posix()


@dataclass(frozen=True, slots=True)
class FFmpegInput:
    """One ``-i`` input, with the options that must precede it.

    ``options`` are the flags FFmpeg requires *before* the input they describe --
    ``-f concat -safe 0`` for a demuxer list, ``-f lavfi`` for a synthetic
    source. They are our own closed vocabulary, never authored content.
    """

    path: Path
    options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FFmpegCommand:
    """An immutable FFmpeg invocation that renders to an ``argv`` list.

    Construction validates every path against ``workspace`` so an escaping path
    fails when the command is *built*, before any process starts. ``argv`` is then
    a pure function of the fields -- deterministic, snapshot-testable, and safe to
    hand straight to :func:`subprocess.run` with ``shell=False``.
    """

    workspace: Path
    output: Path
    inputs: tuple[FFmpegInput, ...] = ()
    filter_complex: str | None = None
    output_options: tuple[str, ...] = ()
    executable: str = "ffmpeg"
    overwrite: bool = True

    def __post_init__(self) -> None:
        # Validate now, so an escaping path is a construction error rather than a
        # surprise deep inside a subprocess call.
        for item in self.inputs:
            workspace_relative(self.workspace, item.path)
        workspace_relative(self.workspace, self.output)

    def argv(self) -> list[str]:
        """The full argument vector, paths relative to the workspace."""
        argv: list[str] = [self.executable]
        if self.overwrite:
            argv.append("-y")
        for item in self.inputs:
            argv.extend(item.options)
            argv.extend(("-i", workspace_relative(self.workspace, item.path)))
        if self.filter_complex is not None:
            argv.extend(("-filter_complex", self.filter_complex))
        argv.extend(self.output_options)
        argv.append(workspace_relative(self.workspace, self.output))
        return argv
