"""The repair agent: diagnostics plus the offending scene in, a JSON Patch out.

Repair is the honest half of the autofix split. Autofix handles what is
mechanically safe; everything semantic -- a cue targeting an object that does not
exist, an op whose signature is unmet, a relationship the skill forbids -- stays a
hard error and arrives here. The agent does not rewrite the scene: it proposes a
minimal :class:`~manorem_ai.patch.JsonPatch`, which is auditable, revertible, and
cannot disturb a scene it was not pointed at.

The load-bearing constraint lives in :func:`~manorem_ai.patch.apply_scene_patch`,
not in this prompt: a patch may fix a reference, a parameter or a time, but it may
not change *which* objects, cues, groups, segments or relationships exist. So even
a model that ignores the instruction cannot fabricate the missing satellite or
quietly drop the dangling cue -- the patch is rejected and the bounded loop moves
on. The prompt asks for the right thing; the type system guarantees it.
"""

from __future__ import annotations

from collections.abc import Sequence

from manorem_ai.agents.base import Agent, load_prompt, render_input
from manorem_ai.patch import JsonPatch
from manorem_ai.provider import Completion
from manorem_core import Diagnostic
from manorem_ir import Scene

__all__ = ["RepairAgent"]


class RepairAgent(Agent):
    """Propose a minimal JSON Patch that clears a scene's semantic diagnostics."""

    def run(
        self, scene: Scene, diagnostics: Sequence[Diagnostic], *, vocabulary: str
    ) -> Completion[JsonPatch]:
        user = render_input(
            scene=scene,
            diagnostics=[d.model_dump(mode="json") for d in diagnostics],
            available_vocabulary=vocabulary,
        )
        return self._complete(system=load_prompt("repair"), user=user, schema=JsonPatch)
