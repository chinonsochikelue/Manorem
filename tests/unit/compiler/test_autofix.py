"""Autofix: mechanically safe only, and it never changes an id set.

The guardrail this module protects is the whole reason autofix is narrow: a fixer
may pad a too-short scene so its narration fits, but it may not invent, drop, or
rename an object, cue, relationship or narration segment. Semantic defects -- an
unknown reference, a missing required object, an impossible relationship -- stay
ERRORs and go to the bounded RepairAgent, because a quietly-repaired render that
omits a satellite is worse than a loud failure.

The id-set invariant is asserted two ways: on a hand-built corpus, and as a
Hypothesis property over generated projects, so a future fixer that starts
touching ids fails here rather than in a render nobody inspects.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from manorem_compiler import autofix_project, compile_project
from manorem_core import Code
from manorem_ir import Project, RelationKind, SemanticOp
from tests.support.diag import error_codes
from tests.support.ir_builders import (
    cue,
    dot_obj,
    make_project,
    make_scene,
    relationship,
    scene_with,
    segment,
    show,
    text_obj,
)

# --- id-set collection -----------------------------------------------------

IdSets = tuple[frozenset[str], frozenset[str], frozenset[str], frozenset[tuple[str, str, str]]]


def _id_sets(project: Project) -> IdSets:
    """The object / cue / narration / relationship identities autofix must preserve."""
    objects: set[str] = set()
    cues: set[str] = set()
    narration: set[str] = set()
    relationships: set[tuple[str, str, str]] = set()
    for episode in project.episodes:
        for scene in episode.scenes:
            objects |= {obj.id for obj in scene.objects} | {grp.id for grp in scene.groups}
            cues |= {c.id for c in scene.timeline}
            narration |= {seg.id for seg in scene.narration}
            relationships |= {(r.kind.value, r.source, r.target) for r in scene.relationships}
    return frozenset(objects), frozenset(cues), frozenset(narration), frozenset(relationships)


# --- permitted: harmless duration padding ----------------------------------


def test_autofix_extends_a_scene_too_short_for_its_narration() -> None:
    short = scene_with(duration_hint=0.1)
    result = autofix_project(make_project(short))
    assert result.changed
    padded = result.project.episodes[0].scenes[0]
    assert padded.duration_hint is not None
    assert padded.duration_hint > 0.1


def test_autofix_leaves_a_well_paced_scene_untouched() -> None:
    # A hint already long enough for the narration is padding-free: autofix only
    # extends, never trims, so a generous hint is a no-op.
    project = make_project(scene_with(duration_hint=10.0))
    result = autofix_project(project)
    assert not result.changed
    assert result.project == project


# --- forbidden: semantic defects stay hard errors --------------------------


def test_autofix_does_not_repair_an_unknown_object_ref() -> None:
    broken = scene_with(timeline=[show("boot", ["title"]), show("ghost_show", ["ghost"])])
    project = make_project(broken)
    fixed = autofix_project(project).project
    # The dangling cue is still there -- autofix did not drop it to look clean.
    assert _id_sets(fixed) == _id_sets(project)
    _, bag = compile_project(project)
    assert Code.IR201_UNKNOWN_OBJECT_REF in error_codes(bag)


def test_autofix_does_not_repair_an_invalid_relationship() -> None:
    scene = make_scene(
        intent="An arrow needs two real endpoints.",
        objects=[text_obj("title"), dot_obj("phone")],
        relationships=[relationship(RelationKind.POINTS_TO, "phone", "nowhere")],
        narration=[segment("line", "One line.")],
        timeline=[show("s1", ["title"]), show("s2", ["phone"])],
    )
    project = make_project(scene)
    fixed = autofix_project(project).project
    assert _id_sets(fixed) == _id_sets(project)
    _, bag = compile_project(project)
    assert error_codes(bag)  # a semantic error fired; autofix did not paper over it


# --- property: id sets are invariant under autofix -------------------------

_slugs = st.from_regex(r"[a-z][a-z0-9_]{0,7}", fullmatch=True)


@st.composite
def _projects(draw: st.DrawFn) -> Project:
    """A constructible project with varied ids and a random, possibly-tiny hint.

    Autofix runs before validation, so these need not be *valid* -- only
    constructible. That is deliberate: the invariant must hold even for the broken
    inputs that reach autofix on the way to the repair loop.
    """
    object_ids = draw(st.lists(_slugs, min_size=1, max_size=4, unique=True))
    narration_ids = draw(st.lists(_slugs, min_size=0, max_size=3, unique=True))
    hint = draw(st.one_of(st.none(), st.floats(min_value=0.05, max_value=20.0)))
    objects = [text_obj(oid, content="x") for oid in object_ids]
    cues = [cue(f"cue_{n}", SemanticOp.SHOW, [object_ids[0]]) for n in range(len(object_ids))]
    narration = [segment(nid, "A line of narration.") for nid in narration_ids]
    scene = make_scene(
        intent="Generated.",
        objects=objects,
        narration=narration,
        timeline=cues,
        duration_hint=hint,
    )
    return make_project(scene)


@given(_projects())
def test_autofix_preserves_all_id_sets(project: Project) -> None:
    result = autofix_project(project)
    assert _id_sets(result.project) == _id_sets(project)
