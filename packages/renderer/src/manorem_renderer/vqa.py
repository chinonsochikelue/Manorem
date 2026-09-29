"""Deterministic Visual QA over the render manifest.

The Visual QA seam exists so the pipeline can answer "the render succeeded, but does
the *frame* satisfy the plan?" -- and the manifest already carries the answer for the
geometric checks, in world coordinates the compiler wrote down so a renderer never has
to measure anything. So these checks are pure functions over :class:`RenderManifest`:
no pixels decoded, no external process, no model call, no network. Deterministic and
offline, and identical across backends because the manifest is.

Two boundaries are deliberate and firm.

* **VQA runs *after* a successful render, on the plan it produced.** A finding is a
  defect in a video that otherwise came out fine -- it is not a compiler fault, so it
  does not surface during ``validate``/``compile``. Conflating them would make a
  structurally-valid plan fail pre-render validation that has no business running there.
* **Findings point at IR-level locations, never renderer internals.** The pointer is a
  JSON Pointer into the plan's scenes/mobjects and ``object_id`` names the mobject, so
  the repair loop can patch the *plan* and rerun -- the same bounded repair the
  semantic errors use. A VQA check may never emit something that would drive a patch to
  ``plan_scene.py`` or ``renderer.py``.

What the manifest does *not* carry (exact rendered glyph shapes, pixel coverage, local
background luminance) determines what these checks cannot see. ``VQA606_BAD_CONTRAST``
therefore scores against the *declared* scene background colour for the mobject kinds
where the compiler knows the foreground colour -- and that limitation is stated, not
hidden.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from manorem_compiler import MobjectSpec, PlanBounds, Primitive, RenderPlan, ScenePlan
from manorem_core import Code, Diagnostic, DiagnosticBag, Severity, pointer
from manorem_renderer.manifest import MANIM_FRAME_HEIGHT
from manorem_renderer.results import (
    FrameManifest,
    MobjectSnapshot,
    QualityReport,
    RenderManifest,
    RenderResult,
    ScenePlanManifest,
)

__all__ = [
    "VQA_ERROR_CODES",
    "GeometricVisualQA",
    "VQAConfig",
    "VQAReport",
    "assess_plan",
]

#: Primitives that draw text -- the ones VQA601/VQA604/VQA606 apply to.
_TEXT_PRIMITIVES: frozenset[Primitive] = frozenset({Primitive.TEXT, Primitive.MATH})

#: Manim's world frame is fixed at 8.0 units tall; width follows from aspect.
_MANIM_FRAME_HEIGHT = MANIM_FRAME_HEIGHT

#: VQA6xx codes emitted at error severity -- the ones the visual-repair loop selects.
#: VQA608/VQA609 are warnings (a note, not a build failure) and are deliberately absent.
VQA_ERROR_CODES: frozenset[Code] = frozenset(
    {
        Code.VQA601_TEXT_OVERFLOW,
        Code.VQA602_OBJECT_OFF_STAGE,
        Code.VQA603_OBJECT_OVERLAP,
        Code.VQA604_TINY_TEXT,
        Code.VQA605_EMPTY_FRAME,
        Code.VQA606_BAD_CONTRAST,
        Code.VQA607_CUT_OFF_OBJECT,
    }
)


def _channel(hex_pair: str) -> float:
    return int(hex_pair, 16) / 255.0


def _relative_luminance(hex_color: str) -> float:
    """Linear-space luminance of a hex colour, per ITU-R BT.709."""
    digits = hex_color.lstrip("#")
    r, g, b = _channel(digits[0:2]), _channel(digits[2:4]), _channel(digits[4:6])

    def _linear(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def _contrast_ratio(fg: str, bg: str) -> float:
    """WCAG contrast ratio between two hex colours: >= 1.0, up to 21.0."""
    l1, l2 = _relative_luminance(fg), _relative_luminance(bg)
    lighter, darker = (l1, l2) if l1 >= l2 else (l2, l1)
    return (lighter + 0.05) / (darker + 0.05)


def _is_hex(value: object) -> bool:
    return isinstance(value, str) and len(value.lstrip("#")) == 6 and value.startswith("#")


@dataclass(frozen=True, slots=True)
class VQAConfig:
    """Configurable thresholds. Each knob bounds a *measurable* quantity.

    Defaults keep M2 honest rather than generous: a scene that is merely "probably
    fine" still surfaces and routes to bounded repair. A project may tighten or relax
    them via settings without changing checks.
    """

    #: Minimum rendered text height (world units) below which text is unreadable even
    #: at the target resolution. Sized so a 1080p render is legible but a 480p draft
    #: cannot silently pass unreadable copy.
    min_text_height: float = 0.35
    #: Per-frame visible-mobject count above which a scene is flagged for density.
    max_objects_per_frame: int = 12
    #: Per-frame share of the frame area occupied by visible mobjects before density
    #: is flagged. 0.65 leaves room for white space / breathing room.
    max_ink_per_frame: float = 0.65
    #: Minimum total area (world units^2) a scene's visible mobjects must occupy to
    #: avoid VQA605_EMPTY_FRAME. Covers intentional title-card fades (background plus
    #: one element) vs. a plan that drew nothing.
    min_scene_area: float = 0.05
    #: Smallest bounding-box edge (world units) below which a partially-out-of-frame
    #: mobject is "off stage" (VQA602) rather than "cut off" (VQA607). Below this it is
    #: too small to be anything but stray geometry.
    off_stage_min_extent: float = 0.01
    #: Intersection area (world units^2) above which two visible, non-grouped, unordered
    #: mobjects overlap. The compiler allows intentional layering through z-order and
    #: grouping, so those pairs never reach this test.
    overlap_tolerance: float = 0.0
    #: Minimum WCAG contrast ratio between text foreground and the declared scene
    #: background below which copy is treated as unreadable. 4.5 is WCAG AA normal text.
    min_contrast_ratio: float = 4.5


#: The default thresholds, materialised once so callers can omit ``cfg`` without
#: constructing a fresh (identical, frozen) config at every call site.
_DEFAULT_CONFIG = VQAConfig()


@dataclass(slots=True)
class VQAReport:
    """The diagnostics one :func:`assess_plan` run produced.

    ``passed`` is True when no error-severity finding was emitted. A warning is a
    note (density high but not alarming) and does not fail a build unless policy
    elects it to.
    """

    findings: tuple[Diagnostic, ...] = ()

    @property
    def passed(self) -> bool:
        return not any(f.severity is Severity.ERROR for f in self.findings)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _viewport(frame: FrameManifest, ratio: float) -> PlanBounds:
    """The world-space box the camera actually shows at this sampled frame.

    Off-stage, cut-off and overflow are judged against *what the camera frames*, not
    a fixed default frame: a zoomed-in camera legitimately narrows the stage, and an
    object outside that narrowed view is genuinely off screen.
    """
    half_w = frame.camera_width / 2.0
    half_h = (frame.camera_width / ratio) / 2.0
    cx, cy, _ = frame.camera_center
    return PlanBounds(min_x=cx - half_w, min_y=cy - half_h, max_x=cx + half_w, max_y=cy + half_h)


def _mobject_area(bounds: PlanBounds) -> float:
    return max(bounds.width, 0.0) * max(bounds.height, 0.0)


def _contained(inner: PlanBounds, outer: PlanBounds) -> bool:
    """Whether ``inner`` lies wholly within ``outer`` (touching edges is inside)."""
    return (
        inner.min_x >= outer.min_x
        and inner.max_x <= outer.max_x
        and inner.min_y >= outer.min_y
        and inner.max_y <= outer.max_y
    )


def _center_inside(bounds: PlanBounds, outer: PlanBounds) -> bool:
    cx, cy = bounds.center
    return outer.min_x <= cx <= outer.max_x and outer.min_y <= cy <= outer.max_y


# ---------------------------------------------------------------------------
# Per-scene assessment
# ---------------------------------------------------------------------------
#
# One pass over the sampled frames. Per-mobject findings dedupe on (code, object_id)
# so a box off-stage for a whole scene is one finding, not one per frame; per-scene
# findings (empty, density, composition) fire at most once, at the first offending
# frame. A synthetic child (a packet, a highlight ring, a graph node) is attributed
# to the authored object that owns it, because that is what the repair loop can patch.


def _assess_scene(
    scene: ScenePlan, sm: ScenePlanManifest, ratio: float, cfg: VQAConfig, bag: DiagnosticBag
) -> None:
    specs: dict[str, MobjectSpec] = {m.id: m for m in scene.mobjects}
    grouped: set[str] = set()
    owner_of: dict[str, str] = {}
    for m in scene.mobjects:
        for child in m.members:
            grouped.add(child)
            owner_of[child] = m.id

    def owner(oid: str) -> str:
        return owner_of.get(oid, oid)

    seen: set[tuple[Code, str]] = set()
    scene_seen: set[Code] = set()

    def once(code: Code, oid: str) -> bool:
        key = (code, oid)
        if key in seen:
            return False
        seen.add(key)
        return True

    for fm in sm.frames:
        view = _viewport(fm, ratio)
        visible = fm.visible_mobjects

        if (
            Code.VQA605_EMPTY_FRAME not in scene_seen
            and sum(_mobject_area(m.bounds) for m in visible) < cfg.min_scene_area
        ):
            scene_seen.add(Code.VQA605_EMPTY_FRAME)
            bag.add(
                Code.VQA605_EMPTY_FRAME,
                f"scene {scene.id!r} draws almost nothing at frame {fm.frame} "
                "(visible mobjects cover less than the minimum scene area)",
                pointer=pointer("scenes", scene.id),
                scene_id=scene.id,
                hint="Add or reveal the scene's content, or shorten the empty interval.",
            )

        _check_mobjects(scene, view, visible, specs, owner=owner, once=once, cfg=cfg, bag=bag)
        _check_overlap(scene, visible, grouped, specs, owner=owner, seen=seen, cfg=cfg, bag=bag)
        _check_density(scene, fm, view, visible, scene_seen=scene_seen, cfg=cfg, bag=bag)
        _check_composition(scene, fm, view, visible, scene_seen=scene_seen, bag=bag)
    # END _assess_scene


def _check_mobjects(
    scene: ScenePlan,
    view: PlanBounds,
    visible: tuple[MobjectSnapshot, ...],
    specs: dict[str, MobjectSpec],
    *,
    owner: Callable[[str], str],
    once: Callable[[Code, str], bool],
    cfg: VQAConfig,
    bag: DiagnosticBag,
) -> None:
    """Per-mobject checks: text legibility/overflow/contrast, and off-stage vs cut-off."""
    for m in visible:
        oid = owner(m.id)
        ptr = pointer("scenes", scene.id, "mobjects", oid)
        if m.primitive in _TEXT_PRIMITIVES:
            if m.bounds.height < cfg.min_text_height and once(Code.VQA604_TINY_TEXT, oid):
                bag.add(
                    Code.VQA604_TINY_TEXT,
                    f"text {oid!r} renders {m.bounds.height:.2f} world units tall, "
                    f"below the {cfg.min_text_height:.2f} legibility floor",
                    pointer=ptr,
                    scene_id=scene.id,
                    object_id=oid,
                    hint="Raise the text role's size or shorten the copy so it fits larger.",
                )
            if not _contained(m.bounds, view) and once(Code.VQA601_TEXT_OVERFLOW, oid):
                bag.add(
                    Code.VQA601_TEXT_OVERFLOW,
                    f"text {oid!r} extends past the framed stage and its glyphs would clip",
                    pointer=ptr,
                    scene_id=scene.id,
                    object_id=oid,
                    hint="Shorten the text, wrap it, or reduce its size so it fits the frame.",
                )
            spec = specs.get(m.id)
            color = spec.args.get("color") if spec is not None else None
            if (
                isinstance(color, str)
                and _is_hex(color)
                and _contrast_ratio(color, scene.background) < cfg.min_contrast_ratio
                and once(Code.VQA606_BAD_CONTRAST, oid)
            ):
                bag.add(
                    Code.VQA606_BAD_CONTRAST,
                    f"text {oid!r} at {color} has contrast "
                    f"{_contrast_ratio(color, scene.background):.1f}:1 against background "
                    f"{scene.background} (below {cfg.min_contrast_ratio:.1f}:1)",
                    pointer=ptr,
                    scene_id=scene.id,
                    object_id=oid,
                    hint="Pick a text colour with more contrast against the scene background.",
                )
        else:
            inter = m.bounds.intersection_area(view)
            if inter <= 0.0:
                if once(Code.VQA602_OBJECT_OFF_STAGE, oid):
                    bag.add(
                        Code.VQA602_OBJECT_OFF_STAGE,
                        f"mobject {oid!r} is entirely outside the framed stage and never seen",
                        pointer=ptr,
                        scene_id=scene.id,
                        object_id=oid,
                        hint="Reposition it inside the safe area, or remove it if unintended.",
                    )
            elif not _contained(m.bounds, view):
                edge = min(m.bounds.width, m.bounds.height)
                if edge < cfg.off_stage_min_extent:
                    if once(Code.VQA602_OBJECT_OFF_STAGE, oid):
                        bag.add(
                            Code.VQA602_OBJECT_OFF_STAGE,
                            f"mobject {oid!r} pokes off-stage and is too small to be anything "
                            "but stray geometry",
                            pointer=ptr,
                            scene_id=scene.id,
                            object_id=oid,
                            hint="Remove the stray element or give it real extent in the frame.",
                        )
                elif once(Code.VQA607_CUT_OFF_OBJECT, oid):
                    bag.add(
                        Code.VQA607_CUT_OFF_OBJECT,
                        f"mobject {oid!r} is partly outside the framed stage and renders cut off",
                        pointer=ptr,
                        scene_id=scene.id,
                        object_id=oid,
                        hint="Move it fully inside the safe area or scale it down to fit.",
                    )


def _check_overlap(
    scene: ScenePlan,
    visible: tuple[MobjectSnapshot, ...],
    grouped: set[str],
    specs: dict[str, MobjectSpec],
    *,
    owner: Callable[[str], str],
    seen: set[tuple[Code, str]],
    cfg: VQAConfig,
    bag: DiagnosticBag,
) -> None:
    """VQA603: two visible mobjects at the same z overlap without being grouped.

    Layering is legitimate when the author asked for it -- a different ``z_index`` or
    membership in a group -- and synthetic elements (a highlight ring over its subject)
    are meant to sit on top. Those pairs are excluded so only accidental collisions fire.
    """
    candidates = [
        m for m in visible if m.id not in grouped and not (m.id in specs and specs[m.id].synthetic)
    ]
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            a, b = candidates[i], candidates[j]
            if a.z_index != b.z_index:
                continue
            if a.bounds.intersection_area(b.bounds) <= cfg.overlap_tolerance:
                continue
            first, second = sorted((owner(a.id), owner(b.id)))
            if first == second:
                continue
            key = (Code.VQA603_OBJECT_OVERLAP, f"{first}|{second}")
            if key in seen:
                continue
            seen.add(key)
            bag.add(
                Code.VQA603_OBJECT_OVERLAP,
                f"mobjects {first!r} and {second!r} overlap on the same layer",
                pointer=pointer("scenes", scene.id, "mobjects", first),
                scene_id=scene.id,
                object_id=first,
                hint="Separate them, group them intentionally, or give one a distinct z-order.",
            )


def _check_density(
    scene: ScenePlan,
    fm: FrameManifest,
    view: PlanBounds,
    visible: tuple[MobjectSnapshot, ...],
    *,
    scene_seen: set[Code],
    cfg: VQAConfig,
    bag: DiagnosticBag,
) -> None:
    """VQA608 (warning): too many mobjects or too much ink on one frame."""
    if Code.VQA608_EXCESSIVE_DENSITY in scene_seen:
        return
    count = len(visible)
    frame_area = view.area
    coverage = (
        sum(_mobject_area(m.bounds) for m in visible) / frame_area if frame_area > 0.0 else 0.0
    )
    if count > cfg.max_objects_per_frame or coverage > cfg.max_ink_per_frame:
        scene_seen.add(Code.VQA608_EXCESSIVE_DENSITY)
        bag.warn(
            Code.VQA608_EXCESSIVE_DENSITY,
            f"scene {scene.id!r} is crowded at frame {fm.frame}: {count} visible mobjects "
            f"covering {coverage:.0%} of the frame",
            pointer=pointer("scenes", scene.id),
            scene_id=scene.id,
            hint="Split the content across scenes, or reveal fewer elements at once.",
        )


def _check_composition(
    scene: ScenePlan,
    fm: FrameManifest,
    view: PlanBounds,
    visible: tuple[MobjectSnapshot, ...],
    *,
    scene_seen: set[Code],
    bag: DiagnosticBag,
) -> None:
    """VQA609 (warning): the camera frames nothing -- no visible subject's centre is in view."""
    if Code.VQA609_CAMERA_COMPOSITION in scene_seen or not visible:
        return
    if not any(_center_inside(m.bounds, view) for m in visible):
        scene_seen.add(Code.VQA609_CAMERA_COMPOSITION)
        bag.warn(
            Code.VQA609_CAMERA_COMPOSITION,
            f"the camera at frame {fm.frame} centres on empty space -- no visible subject "
            "falls under the frame centre",
            pointer=pointer("scenes", scene.id),
            scene_id=scene.id,
            hint="Point the camera at a subject, or widen the frame to include one.",
        )


def assess_plan(
    plan: RenderPlan, manifest: RenderManifest, cfg: VQAConfig = _DEFAULT_CONFIG
) -> VQAReport:
    """Assess a rendered plan against its manifest, purely from the geometry it carries.

    Returns a :class:`VQAReport`; error-severity findings are the ones the pipeline's
    visual-repair loop routes back to IR repair (see :data:`VQA_ERROR_CODES`).
    """
    bag = DiagnosticBag()
    ratio = plan.format.aspect.ratio
    for scene in plan.scenes:
        sm = manifest.scene(scene.id)
        if sm is None:
            continue
        _assess_scene(scene, sm, ratio, cfg, bag)
    return VQAReport(findings=tuple(bag.sorted()))


class GeometricVisualQA:
    """A real Visual QA backend: the deterministic geometric checks, wired to a render.

    Structurally satisfies :class:`manorem_ai.quality.VisualQA`. It assesses only a
    render that *completed* -- ``status`` OK, an actual video on disk. A failed or
    timed-out render is left *not assessed* (``None``): its manifest describes a video
    that does not exist, so scoring it would invent a verdict about nothing. That keeps
    the ``None`` = not-assessed contract intact rather than reporting a spurious pass.
    """

    name = "geometric"

    def __init__(self, config: VQAConfig | None = None) -> None:
        self._config = config or VQAConfig()

    def assess(self, plan: RenderPlan, result: RenderResult) -> QualityReport | None:
        if not result.ok:
            return None
        report = assess_plan(plan, result.manifest, self._config)
        return QualityReport(findings=report.findings)
