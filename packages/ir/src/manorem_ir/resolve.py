"""Symbolic timing resolution.

Turns relative timing expressions into seconds-from-scene-start. This lives in
the IR package rather than the compiler because *two* consumers need it and they
must not disagree: the T2/T3 validators report timing defects, and compiler pass
P4 quantizes the same numbers to frames. One implementation, two callers.

What this module does **not** do: quantize to frames, expand skill macros, or
clamp anything. Those are the compiler's business.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from manorem_ir.narration import DEFAULT_WPM, NarrationSegment
from manorem_ir.operations import DEFAULT_REGISTRY, OperationRegistry
from manorem_ir.scene import Scene
from manorem_ir.timeline import Cue
from manorem_ir.timing import (
    AbsoluteTime,
    AfterCue,
    AutoDuration,
    NarrationDuration,
    NarrationTime,
    SecondsDuration,
    WithCue,
)

#: Fallback length for a cue whose operation has no declaration. Only reached
#: when the op is already flagged as unknown (IR205), so it exists purely to keep
#: resolution total instead of raising mid-validation.
FALLBACK_DURATION = 1.0


@dataclass(frozen=True, slots=True)
class Window:
    """A half-open interval on the scene's local clock, in seconds."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def overlaps(self, other: Window) -> bool:
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True, slots=True)
class ResolvedTiming:
    """Best-effort schedule for one scene.

    ``unresolved`` is deliberately explicit rather than defaulted to zero: a cue
    whose time could not be determined is a defect to report, not a cue that
    happens to start at the beginning.
    """

    starts: dict[str, float]
    durations: dict[str, float]
    narration: dict[str, Window]
    unresolved: frozenset[str]
    cycles: tuple[tuple[str, ...], ...]

    def window(self, cue_id: str) -> Window | None:
        start = self.starts.get(cue_id)
        if start is None:
            return None
        return Window(start=start, end=start + self.durations.get(cue_id, 0.0))

    @property
    def end(self) -> float:
        """When the last resolved cue finishes. Zero for an empty timeline."""
        ends = [self.starts[c] + self.durations.get(c, 0.0) for c in self.starts]
        return max(ends, default=0.0)


def narration_windows(scene: Scene, wpm: float = DEFAULT_WPM) -> dict[str, Window]:
    """Lay narration segments end to end, honouring any measured timings.

    A segment carrying both ``start`` and ``end`` has been timed for real (by a
    retime pass against rendered audio) and is used verbatim; the rest fall back
    to the words-per-minute estimate. Mixing the two is intentional -- it is what
    lets TTS timings replace estimates segment by segment.
    """
    windows: dict[str, Window] = {}
    cursor = 0.0
    for segment in scene.narration:
        if segment.start is not None and segment.end is not None:
            window = Window(start=segment.start, end=segment.end)
        else:
            window = Window(start=cursor, end=cursor + segment.estimated_duration(wpm))
        windows[segment.id] = window
        cursor = window.end
    return windows


def retime_narration(scene: Scene, durations: Mapping[str, float]) -> Scene:
    """Return a copy of ``scene`` whose segments carry measured ``start``/``end``.

    Each segment present in ``durations`` is laid end-to-end on the scene-local
    clock from its *measured* speaking time plus the authored ``pause_after``::

        window = [cursor, cursor + durations[seg.id] + seg.pause_after]

    which is exactly the shape :func:`narration_windows` later reproduces from the
    stored ``start``/``end`` -- so once a scene is retimed, every downstream
    consumer (cue anchoring, frame quantization, subtitles) reads the same clock
    with no second timing system.

    This is a pure primitive. ``durations`` *may* be partial: a segment absent
    from the map keeps its current state (``start``/``end`` untouched, so it falls
    back to the WPM estimate), and the cursor advances by that segment's own
    estimate so any remaining measured segments stay laid end to end. The pipeline
    never passes a partial scene -- a failed scene is retimed with an empty map
    (all WPM) and a succeeded scene with a complete one -- but the partiality keeps
    the primitive total and testable.
    """
    cursor = 0.0
    retimed: list[NarrationSegment] = []
    for segment in scene.narration:
        measured = durations.get(segment.id)
        if measured is None:
            retimed.append(segment)
            cursor += segment.estimated_duration()
            continue
        start = cursor
        end = cursor + measured + segment.pause_after
        retimed.append(segment.with_timing(start, end))
        cursor = end
    return scene.model_copy(update={"narration": retimed})


def _find_cycles(edges: dict[str, str]) -> tuple[tuple[str, ...], ...]:
    """Cycles in the cue dependency graph, where each cue has at most one parent.

    With one outgoing edge per node, following the chain from any node either
    terminates or repeats -- so a plain walk with a visited set finds every cycle
    without needing a full SCC decomposition.
    """
    cycles: list[tuple[str, ...]] = []
    seen: set[str] = set()
    for node in edges:
        if node in seen:
            continue
        path: list[str] = []
        index: dict[str, int] = {}
        current: str | None = node
        while current is not None and current not in seen:
            if current in index:
                cycles.append(tuple(path[index[current] :]))
                break
            index[current] = len(path)
            path.append(current)
            current = edges.get(current)
        seen.update(path)
    return tuple(cycles)


def _resolve_durations(
    cues: dict[str, Cue], windows: dict[str, Window], registry: OperationRegistry
) -> dict[str, float]:
    """Length of each cue, omitting any whose narration segment does not exist."""
    durations: dict[str, float] = {}
    for cue_id, cue in cues.items():
        spec = cue.duration
        if isinstance(spec, SecondsDuration):
            durations[cue_id] = spec.seconds
        elif isinstance(spec, NarrationDuration):
            window = windows.get(spec.segment)
            if window is not None:
                durations[cue_id] = window.duration
        elif isinstance(spec, AutoDuration):
            decl = registry.get(cue.op)
            durations[cue_id] = decl.default_duration if decl else FALLBACK_DURATION
    return durations


def _start_of(
    cue: Cue, starts: dict[str, float], durations: dict[str, float], windows: dict[str, Window]
) -> float | None:
    """One cue's start, or None while its dependency is still unresolved."""
    at = cue.at
    if isinstance(at, AbsoluteTime):
        return at.seconds
    if isinstance(at, AfterCue):
        base = starts.get(at.cue)
        length = durations.get(at.cue)
        return None if base is None or length is None else base + length + at.gap
    if isinstance(at, WithCue):
        base = starts.get(at.cue)
        return None if base is None else base + at.offset
    if isinstance(at, NarrationTime):
        window = windows.get(at.segment)
        if window is None:
            return None
        edge = window.start if at.edge == "start" else window.end
        return edge + at.offset
    return None


def resolve_timing(
    scene: Scene,
    *,
    registry: OperationRegistry = DEFAULT_REGISTRY,
    wpm: float = DEFAULT_WPM,
) -> ResolvedTiming:
    """Resolve every cue's start and duration, reporting what could not be.

    Resolution is iterated to a fixpoint rather than topologically sorted, so a
    partially broken timeline still yields useful times for the cues that *are*
    well-formed -- which is what makes the diagnostics specific instead of
    collapsing into one "timeline is broken".
    """
    windows = narration_windows(scene, wpm)
    cues = {c.id: c for c in scene.timeline}
    durations = _resolve_durations(cues, windows, registry)

    starts: dict[str, float] = {}
    pending = set(cues)
    # Each iteration resolves at least one cue or nothing changes; bounded by the
    # cue count, so a cyclic timeline terminates instead of spinning.
    for _ in range(len(cues) + 1):
        progressed = False
        for cue_id in sorted(pending):
            resolved = _start_of(cues[cue_id], starts, durations, windows)
            if resolved is not None:
                starts[cue_id] = resolved
                pending.discard(cue_id)
                progressed = True
        if not progressed:
            break

    edges: dict[str, str] = {}
    for cue_id, cue in cues.items():
        parent = cue.depends_on_cue
        if parent is not None:
            edges[cue_id] = parent

    return ResolvedTiming(
        starts=starts,
        durations=durations,
        narration=windows,
        unresolved=frozenset(pending),
        cycles=_find_cycles(edges),
    )
