"""Scenes: the unit of authoring, rendering, caching and repair.

A scene is deliberately self-contained -- objects, layout, camera, narration and
timeline all live here and reference nothing outside. That is what makes
per-scene AI generation possible (Gemini's schema nesting limits rule out
whole-project generation), per-scene re-rendering cheap, and repair local: a
JSON Patch fixing scene 4 cannot disturb scene 7.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from manorem_core import Slug
from manorem_ir.camera import CameraSpec
from manorem_ir.enums import TransitionKind
from manorem_ir.layout import LayoutSpec
from manorem_ir.narration import DEFAULT_WPM, NarrationSegment
from manorem_ir.objects import Group, Relationship, SceneObject
from manorem_ir.timeline import Cue


class Transition(BaseModel):
    """How a scene boundary is crossed. Applied by the compositor, not Manim."""

    model_config = ConfigDict(frozen=True)

    kind: TransitionKind = TransitionKind.CUT
    duration: float = Field(default=0.0, ge=0.0, le=5.0)

    @property
    def overlaps(self) -> bool:
        """Crossfades consume time from both neighbours; cuts do not."""
        return self.kind is TransitionKind.CROSSFADE and self.duration > 0.0


CUT = Transition()


class Scene(BaseModel):
    """One beat of the video."""

    model_config = ConfigDict(frozen=True)

    id: Slug
    name: str = Field(min_length=1, max_length=120)
    #: What this scene is *for*. Read by the visual planner, carried into repair
    #: prompts, and the reference point for a future narration/visual check.
    intent: str = Field(default="", max_length=500)
    #: Desired length. Advisory: the scheduler extends a scene that cannot fit
    #: its narration rather than truncating the voice-over.
    duration_hint: float | None = Field(default=None, gt=0.0, le=600.0)
    #: Skill packs whose vocabulary this scene may use. Restricting the menu
    #: per scene is what keeps generation accurate.
    skills: list[str] = Field(default_factory=lambda: ["core"], max_length=8)

    objects: list[SceneObject] = Field(default_factory=list, max_length=200)
    groups: list[Group] = Field(default_factory=list, max_length=50)
    relationships: list[Relationship] = Field(default_factory=list, max_length=400)

    layout: LayoutSpec = Field(default_factory=LayoutSpec)
    camera: CameraSpec = Field(default_factory=CameraSpec)

    narration: list[NarrationSegment] = Field(default_factory=list, max_length=50)
    timeline: list[Cue] = Field(default_factory=list, max_length=300)

    transition_in: Transition = Field(default=CUT)
    transition_out: Transition = Field(default=CUT)
    #: Style-token role name or None to inherit the project background.
    background: str | None = Field(default=None, max_length=32)

    # --- lookups used by validators and compiler passes ---------------------

    @property
    def object_ids(self) -> set[str]:
        return {o.id for o in self.objects}

    @property
    def group_ids(self) -> set[str]:
        return {g.id for g in self.groups}

    @property
    def cue_ids(self) -> set[str]:
        return {c.id for c in self.timeline}

    @property
    def segment_ids(self) -> set[str]:
        return {s.id for s in self.narration}

    @property
    def addressable_ids(self) -> set[str]:
        """Ids a cue may target: objects and groups both count."""
        return self.object_ids | self.group_ids

    def object_by_id(self, object_id: str) -> SceneObject | None:
        return next((o for o in self.objects if o.id == object_id), None)

    def group_by_id(self, group_id: str) -> Group | None:
        return next((g for g in self.groups if g.id == group_id), None)

    def cue_by_id(self, cue_id: str) -> Cue | None:
        return next((c for c in self.timeline if c.id == cue_id), None)

    def segment_by_id(self, segment_id: str) -> NarrationSegment | None:
        return next((s for s in self.narration if s.id == segment_id), None)

    def resolve_targets(self, target_id: str) -> list[str]:
        """Expand a cue target to the object ids it ultimately refers to.

        A group target means every member; an object target means itself. Returns
        an empty list for an unknown id -- reference validation reports that, and
        this method must not invent a plausible substitute.
        """
        group = self.group_by_id(target_id)
        if group is not None:
            return list(group.members)
        return [target_id] if target_id in self.object_ids else []

    def estimated_narration_duration(self, wpm: float = DEFAULT_WPM) -> float:
        return sum(s.estimated_duration(wpm) for s in self.narration)
