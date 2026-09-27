"""Project and episode: the top of the IR tree.

``Project`` is the unit the pipeline versions and content-addresses. It carries
``ir_version`` so a stored project written by an older build can be recognized
and migrated rather than mis-parsed -- IR is persisted, and persisted schemas
change.
"""

from __future__ import annotations

from collections.abc import Iterator

from pydantic import BaseModel, ConfigDict, Field

from manorem_core import Slug, sha256_of
from manorem_ir.audio import AudioTimeline
from manorem_ir.format import FormatSpec, StyleTokens
from manorem_ir.narration import DEFAULT_WPM
from manorem_ir.scene import Scene

#: Bumped on any breaking change to the IR schema. Minor additions that older
#: readers can ignore do not bump it; anything that changes the meaning of an
#: existing field does.
IR_VERSION = "1.0"


class Episode(BaseModel):
    """An ordered run of scenes rendered into one video file."""

    model_config = ConfigDict(frozen=True)

    id: Slug
    title: str = Field(min_length=1, max_length=200)
    scenes: list[Scene] = Field(default_factory=list, max_length=200)
    #: Built by the compositor stage; absent in authored IR.
    audio: AudioTimeline | None = None

    @property
    def scene_ids(self) -> list[str]:
        return [s.id for s in self.scenes]

    def scene_by_id(self, scene_id: str) -> Scene | None:
        return next((s for s in self.scenes if s.id == scene_id), None)

    def estimated_duration(self, wpm: float = DEFAULT_WPM) -> float:
        """Rough runtime from narration alone -- a planning aid, not the schedule.

        The authoritative duration is the compiled RenderPlan's summed frames.
        """
        return sum(
            s.duration_hint if s.duration_hint is not None else s.estimated_narration_duration(wpm)
            for s in self.scenes
        )


class Project(BaseModel):
    """The whole authored work: the artifact the AI produces and a human edits."""

    model_config = ConfigDict(frozen=True)

    ir_version: str = Field(default=IR_VERSION, pattern=r"^\d+\.\d+$")
    id: Slug
    title: str = Field(min_length=1, max_length=200)
    #: The original natural-language request, kept for provenance and for repair
    #: prompts that need to know what the video was supposed to be about.
    idea: str = Field(default="", max_length=2000)
    style: StyleTokens = Field(default_factory=StyleTokens)
    format: FormatSpec = Field(default_factory=FormatSpec)
    episodes: list[Episode] = Field(default_factory=list, max_length=20)
    narration_wpm: float = Field(default=DEFAULT_WPM, gt=40.0, le=400.0)

    @property
    def scenes(self) -> Iterator[Scene]:
        """Every scene across every episode, in order."""
        for episode in self.episodes:
            yield from episode.scenes

    @property
    def scene_count(self) -> int:
        return sum(len(e.scenes) for e in self.episodes)

    def episode_by_id(self, episode_id: str) -> Episode | None:
        return next((e for e in self.episodes if e.id == episode_id), None)

    def locate_scene(self, scene_id: str) -> tuple[Episode, Scene] | None:
        """Find a scene and its owning episode -- scene ids are project-unique."""
        for episode in self.episodes:
            scene = episode.scene_by_id(scene_id)
            if scene is not None:
                return (episode, scene)
        return None

    def content_hash(self) -> str:
        """Content address of this project. Identical IR always hashes alike."""
        return sha256_of(self)

    def with_format(self, format_spec: FormatSpec) -> Project:
        """Retarget to another aspect or quality.

        Nothing else changes: layout is authored in stage space, so the same IR
        is the input for 16:9, 9:16 and 1:1 alike.
        """
        return self.model_copy(update={"format": format_spec})
