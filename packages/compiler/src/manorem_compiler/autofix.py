"""Mechanically safe repair, before validation and before any model runs.

Autofix exists to absorb the harmless, not to rescue the broken. It runs on authored
IR ahead of validation, and its mandate is deliberately narrow: normalization that
changes presentation, and padding that only ever adds slack. The moment a "fix" would
change *what the video means* -- drop a dangling cue, invent a missing object, retarget
a broken reference -- it is out of scope by design and stays an error for the bounded
repair agent to face honestly. A render that quietly omits the third satellite is a
worse outcome than one that fails loudly.

The line is not a matter of discipline; it is enforced by type. A diagnostic is
autofixable only when it is not an error *and* its code is not in
:data:`~manorem_core.SEMANTIC_ERROR_CODES` -- and that property is derived, never
set by whoever raised the diagnostic. This module never touches a semantic defect, so
the two can never be confused.

**The invariant that makes this checkable:** autofix must not change the set of object,
cue, relationship, or narration-segment ids in the project. A property test asserts it
over the whole example corpus. Every transform here either edits a scalar field or
extends a duration; none adds, removes, or renames an addressable thing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from manorem_ir import Project

__all__ = ["AutofixResult", "autofix_project"]

#: Upper bound on a scene's ``duration_hint``, from the IR field's own constraint.
#: A narration long enough to exceed it is an authoring problem a pacing lint will
#: report; padding cannot fix it and must not write an out-of-range value.
_MAX_HINT_SECONDS = 600.0

#: One mechanically safe transform: a whole project in, the same project (possibly
#: edited) out, with a human-readable note per change it made.
_Autofixer = Callable[[Project], tuple[Project, list[str]]]


@dataclass(frozen=True, slots=True)
class AutofixResult:
    """The repaired project and a record of every change, for logging and tests."""

    project: Project
    applied: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.applied)


def _fit_scene_durations(project: Project) -> tuple[Project, list[str]]:
    """Extend any scene whose hint is too short to hold its own narration.

    Padding only: a hint already long enough is left alone, and a scene with no
    narration is untouched. Extending never drops a beat -- the worst case is a beat
    of silence at the end, which a pacing lint will flag but which no one will mistake
    for a missing satellite.
    """
    notes: list[str] = []
    episodes = list(project.episodes)
    for ep_index, episode in enumerate(episodes):
        scenes = list(episode.scenes)
        changed = False
        for sc_index, scene in enumerate(scenes):
            needed = scene.estimated_narration_duration(project.narration_wpm)
            if needed <= 0.0:
                continue
            target = min(needed, _MAX_HINT_SECONDS)
            if scene.duration_hint is not None and scene.duration_hint >= target:
                continue
            scenes[sc_index] = scene.model_copy(update={"duration_hint": target})
            changed = True
            notes.append(
                f"extended scene {scene.id!r} duration_hint to {target:.2f}s to fit narration"
            )
        if changed:
            episodes[ep_index] = episode.model_copy(update={"scenes": scenes})
    if not notes:
        return project, notes
    return project.model_copy(update={"episodes": episodes}), notes


#: Every mechanically safe transform, applied in order. New autofixers register here;
#: each must preserve the project's object/cue/relationship/narration id sets.
_AUTOFIXERS: tuple[_Autofixer, ...] = (_fit_scene_durations,)


def autofix_project(project: Project) -> AutofixResult:
    """Apply every mechanically safe transform, folding one into the next."""
    applied: list[str] = []
    current = project
    for fix in _AUTOFIXERS:
        current, notes = fix(current)
        applied.extend(notes)
    return AutofixResult(project=current, applied=tuple(applied))
