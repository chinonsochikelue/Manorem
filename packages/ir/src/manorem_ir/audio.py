"""Audio timeline.

Audio is described here and mixed by the compositor -- it never enters the visual
renderer, which emits silent scene videos. That separation is what lets a scene
be re-rendered without touching the mix, and the mix be rebuilt without
re-rendering.

M1 produces no audio files: narration is timed but silent, and these models carry
the structure so that adding TTS changes durations, not architecture.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from manorem_core import Slug


class AudioClip(BaseModel):
    """A sound placed at an absolute time on the final timeline.

    ``asset`` is a storage key resolved through the object store, never a
    filesystem path -- the compositor refuses anything outside the workspace.
    """

    model_config = ConfigDict(frozen=True)

    id: Slug
    asset: str = Field(min_length=1, max_length=512)
    start: float = Field(ge=0.0, le=36000.0, description="Seconds from episode start")
    gain_db: float = Field(default=0.0, ge=-60.0, le=12.0)
    fade_in: float = Field(default=0.0, ge=0.0, le=10.0)
    fade_out: float = Field(default=0.0, ge=0.0, le=10.0)
    kind: Literal["narration", "sfx"] = "sfx"


class MusicBed(BaseModel):
    """Background music, ducked under narration by the compositor."""

    model_config = ConfigDict(frozen=True)

    asset: str = Field(min_length=1, max_length=512)
    gain_db: float = Field(default=-18.0, ge=-60.0, le=0.0)
    duck_db: float = Field(
        default=-8.0,
        ge=-40.0,
        le=0.0,
        description="Additional attenuation applied while narration plays.",
    )
    fade_in: float = Field(default=1.0, ge=0.0, le=10.0)
    fade_out: float = Field(default=2.0, ge=0.0, le=10.0)
    loop: bool = True


class AudioTimeline(BaseModel):
    """Everything the compositor needs to build the mix."""

    model_config = ConfigDict(frozen=True)

    clips: list[AudioClip] = Field(default_factory=list, max_length=500)
    music: MusicBed | None = None
    master_gain_db: float = Field(default=0.0, ge=-30.0, le=12.0)

    @property
    def is_silent(self) -> bool:
        """True in M1: timings exist, audio assets do not."""
        return not self.clips and self.music is None
