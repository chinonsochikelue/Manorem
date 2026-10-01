"""The single diagnostic vocabulary shared by every subsystem.

One type, one code namespace. Validators, the compiler, the renderer and (later)
Visual QA all emit ``Diagnostic``; the repair agent consumes exactly this and
nothing else. Adding a failure mode means adding a code here, which is what makes
"one test per diagnostic code" a checkable rule rather than an aspiration.
"""

from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Code(StrEnum):
    """Namespaced diagnostic codes.

    ``IR1xx`` structural, ``IR2xx`` referential/semantic, ``IR3xx`` pacing and
    geometry, ``CMP4xx`` compile, ``RND5xx`` render, ``VQA6xx`` visual quality,
    ``MUX7xx`` compositing (concat, audio mux, subtitles), ``RES8xx`` research
    provenance, ``AUD9xx`` speech synthesis and audio timing.
    """

    # --- IR1xx: structural (shape of the document) ---------------------------
    IR101_SCHEMA_INVALID = "IR101_SCHEMA_INVALID"
    IR102_DUPLICATE_ID = "IR102_DUPLICATE_ID"
    IR103_INVALID_ID = "IR103_INVALID_ID"
    IR104_EMPTY_SCENE = "IR104_EMPTY_SCENE"
    IR105_NON_POSITIVE_DURATION = "IR105_NON_POSITIVE_DURATION"
    IR106_NO_SCENES = "IR106_NO_SCENES"

    # --- IR2xx: referential / semantic (meaning of the document) -------------
    # Everything in this block is an ERROR that autofix must never "clean up".
    IR201_UNKNOWN_OBJECT_REF = "IR201_UNKNOWN_OBJECT_REF"
    IR202_UNKNOWN_CUE_REF = "IR202_UNKNOWN_CUE_REF"
    IR203_UNKNOWN_NARRATION_REF = "IR203_UNKNOWN_NARRATION_REF"
    IR204_TIMELINE_CYCLE = "IR204_TIMELINE_CYCLE"
    IR205_UNKNOWN_OP = "IR205_UNKNOWN_OP"
    IR206_TARGET_KIND_NOT_ALLOWED = "IR206_TARGET_KIND_NOT_ALLOWED"
    IR207_USE_BEFORE_SHOW = "IR207_USE_BEFORE_SHOW"
    IR208_INVALID_RELATIONSHIP = "IR208_INVALID_RELATIONSHIP"
    IR209_UNSATISFIED_SKILL_CONSTRAINT = "IR209_UNSATISFIED_SKILL_CONSTRAINT"
    IR210_UNKNOWN_SKILL = "IR210_UNKNOWN_SKILL"
    IR211_MISSING_REQUIRED_PARAM = "IR211_MISSING_REQUIRED_PARAM"
    IR212_UNKNOWN_GROUP_MEMBER = "IR212_UNKNOWN_GROUP_MEMBER"
    IR213_UNKNOWN_LAYOUT_SLOT = "IR213_UNKNOWN_LAYOUT_SLOT"
    IR214_TARGET_COUNT_MISMATCH = "IR214_TARGET_COUNT_MISMATCH"
    IR215_UNKNOWN_OBJECT_KIND = "IR215_UNKNOWN_OBJECT_KIND"

    # --- IR3xx: pacing and geometry lints (well-formed but questionable) -----
    IR301_NARRATION_OVERFLOW = "IR301_NARRATION_OVERFLOW"
    IR302_DEAD_AIR = "IR302_DEAD_AIR"
    IR303_SCENE_TOO_DENSE = "IR303_SCENE_TOO_DENSE"
    IR304_OBJECT_OVERLAP = "IR304_OBJECT_OVERLAP"
    IR305_OFF_STAGE = "IR305_OFF_STAGE"
    IR306_SCENE_TOO_SHORT = "IR306_SCENE_TOO_SHORT"

    # --- CMP4xx: compile ----------------------------------------------------
    CMP401_LAYOUT_UNSOLVABLE = "CMP401_LAYOUT_UNSOLVABLE"
    CMP402_UNSUPPORTED_INTENT = "CMP402_UNSUPPORTED_INTENT"
    CMP403_NON_FINITE_VALUE = "CMP403_NON_FINITE_VALUE"
    CMP404_OP_NOT_IN_ALLOWLIST = "CMP404_OP_NOT_IN_ALLOWLIST"
    CMP405_EVENT_PAST_SCENE_END = "CMP405_EVENT_PAST_SCENE_END"
    CMP406_ZERO_DURATION_EVENT = "CMP406_ZERO_DURATION_EVENT"
    CMP407_UNRESOLVED_TIME = "CMP407_UNRESOLVED_TIME"
    CMP408_UNSAFE_ASSET_KEY = "CMP408_UNSAFE_ASSET_KEY"

    # --- RND5xx: render -----------------------------------------------------
    RND501_RENDERER_FAILED = "RND501_RENDERER_FAILED"
    RND502_RENDER_TIMEOUT = "RND502_RENDER_TIMEOUT"
    RND503_ASSET_NOT_FOUND = "RND503_ASSET_NOT_FOUND"
    RND504_PLAN_REJECTED = "RND504_PLAN_REJECTED"

    # --- VQA6xx: visual quality (deterministic geometry + frame-sample checks) --
    # Emitted by the Visual QA seam AFTER a render, never by the compiler. These are
    # visual defects in a succeeded render, not semantic IR damage, so they are not in
    # SEMANTIC_ERROR_CODES -- but error-severity VQA6xx findings still halt a build and
    # route to bounded repair, because they name IR-fixable locations (pointer +
    # object_id), never renderer internals. INFO-level codes describe a state worth
    # recording without blocking.
    VQA601_TEXT_OVERFLOW = "VQA601_TEXT_OVERFLOW"
    VQA602_OBJECT_OFF_STAGE = "VQA602_OBJECT_OFF_STAGE"
    VQA603_OBJECT_OVERLAP = "VQA603_OBJECT_OVERLAP"
    VQA604_TINY_TEXT = "VQA604_TINY_TEXT"
    VQA605_EMPTY_FRAME = "VQA605_EMPTY_FRAME"
    VQA606_BAD_CONTRAST = "VQA606_BAD_CONTRAST"
    VQA607_CUT_OFF_OBJECT = "VQA607_CUT_OFF_OBJECT"
    VQA608_EXCESSIVE_DENSITY = "VQA608_EXCESSIVE_DENSITY"
    VQA609_CAMERA_COMPOSITION = "VQA609_CAMERA_COMPOSITION"

    # --- MUX7xx: compositing (concat, audio mux, subtitles) -----------------
    MUX701_COMPOSITE_FAILED = "MUX701_COMPOSITE_FAILED"
    MUX702_MISSING_INPUT = "MUX702_MISSING_INPUT"
    MUX703_AUDIO_MUX_FAILED = "MUX703_AUDIO_MUX_FAILED"

    # --- AUD9xx: speech synthesis / audio timing ----------------------------
    # Emitted by the TTS seam when synthesizing narration. None of these are
    # semantic: a synthesis failure triggers a *fallback* to WPM estimation, never
    # LLM IR repair, so they stay out of SEMANTIC_ERROR_CODES and remain autofixable
    # (i.e. non-blocking). The audio path is additive -- a clean build with audio
    # disabled emits none of them.
    AUD901_TTS_PROVIDER_FAILED = "AUD901_TTS_PROVIDER_FAILED"
    AUD902_AUDIO_DURATION_INVALID = "AUD902_AUDIO_DURATION_INVALID"
    AUD903_WPM_FALLBACK = "AUD903_WPM_FALLBACK"

    # --- RES8xx: research provenance ----------------------------------------
    # Provenance only: RES801 proves a cited URL was NOT retrieved. It says
    # nothing about whether a retrieved source supports the claim -- that is a
    # future research-layer capability, deliberately not implied here.
    RES801_UNRETRIEVED_SOURCE = "RES801_UNRETRIEVED_SOURCE"


#: Codes describing semantic damage. Autofix is forbidden from touching anything
#: in this set -- they escalate to the bounded repair agent instead. Silently
#: "fixing" a dangling reference discards authorial intent and hides a real
#: planner defect behind a plausible-looking render.
SEMANTIC_ERROR_CODES: frozenset[Code] = frozenset(
    {
        Code.IR201_UNKNOWN_OBJECT_REF,
        Code.IR202_UNKNOWN_CUE_REF,
        Code.IR203_UNKNOWN_NARRATION_REF,
        Code.IR204_TIMELINE_CYCLE,
        Code.IR205_UNKNOWN_OP,
        Code.IR206_TARGET_KIND_NOT_ALLOWED,
        Code.IR207_USE_BEFORE_SHOW,
        Code.IR208_INVALID_RELATIONSHIP,
        Code.IR209_UNSATISFIED_SKILL_CONSTRAINT,
        Code.IR210_UNKNOWN_SKILL,
        Code.IR211_MISSING_REQUIRED_PARAM,
        Code.IR212_UNKNOWN_GROUP_MEMBER,
        Code.IR213_UNKNOWN_LAYOUT_SLOT,
        Code.IR214_TARGET_COUNT_MISMATCH,
        Code.IR215_UNKNOWN_OBJECT_KIND,
    }
)


class Diagnostic(BaseModel):
    """A single machine-actionable finding, addressed by JSON Pointer."""

    model_config = ConfigDict(frozen=True)

    code: Code
    severity: Severity
    message: str
    pointer: str = Field(
        default="", description="RFC 6901 JSON Pointer into the offending document"
    )
    scene_id: str | None = None
    object_id: str | None = None
    hint: str | None = None

    @property
    def autofixable(self) -> bool:
        """Whether a deterministic rule may repair this without an LLM.

        Derived, never stored: a semantic error cannot be relabelled as
        autofixable by whoever happens to construct the diagnostic.
        """
        return self.severity is not Severity.ERROR and self.code not in SEMANTIC_ERROR_CODES

    def __str__(self) -> str:
        where = self.pointer or "/"
        scene = f" [{self.scene_id}]" if self.scene_id else ""
        return f"{self.severity.value}: {self.code.value}{scene} at {where}: {self.message}"


class DiagnosticBag:
    """Accumulator passed through validation and compilation passes."""

    __slots__ = ("_items",)

    def __init__(self, items: list[Diagnostic] | None = None) -> None:
        self._items: list[Diagnostic] = list(items or [])

    def add(
        self,
        code: Code,
        message: str,
        *,
        severity: Severity = Severity.ERROR,
        pointer: str = "",
        scene_id: str | None = None,
        object_id: str | None = None,
        hint: str | None = None,
    ) -> None:
        self._items.append(
            Diagnostic(
                code=code,
                severity=severity,
                message=message,
                pointer=pointer,
                scene_id=scene_id,
                object_id=object_id,
                hint=hint,
            )
        )

    def warn(
        self,
        code: Code,
        message: str,
        *,
        pointer: str = "",
        scene_id: str | None = None,
        object_id: str | None = None,
        hint: str | None = None,
    ) -> None:
        self.add(
            code,
            message,
            severity=Severity.WARNING,
            pointer=pointer,
            scene_id=scene_id,
            object_id=object_id,
            hint=hint,
        )

    def extend(self, other: DiagnosticBag | list[Diagnostic]) -> None:
        self._items.extend(other.items if isinstance(other, DiagnosticBag) else other)

    @property
    def items(self) -> list[Diagnostic]:
        return list(self._items)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self._items if d.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self._items if d.severity is Severity.WARNING]

    @property
    def has_errors(self) -> bool:
        return any(d.severity is Severity.ERROR for d in self._items)

    def codes(self) -> set[Code]:
        return {d.code for d in self._items}

    def sorted(self) -> Self:
        order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
        return type(self)(sorted(self._items, key=lambda d: (order[d.severity], d.code, d.pointer)))

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[Diagnostic]:
        return iter(self._items)

    def __repr__(self) -> str:
        return f"DiagnosticBag({len(self.errors)} errors, {len(self.warnings)} warnings)"


def pointer(*parts: str | int) -> str:
    """Build an RFC 6901 JSON Pointer, escaping ``~`` and ``/`` per spec."""
    out = ""
    for part in parts:
        token = str(part).replace("~", "~0").replace("/", "~1")
        out += f"/{token}"
    return out
