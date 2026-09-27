"""Visual Skills: the domain vocabularies a scene may be written against.

A skill bundles what one subject area needs -- which object kinds exist, which
semantic operations apply, the rules only that domain knows, the layout solvers and
macro expansions that realize it, and the prose that teaches a model to use it. Four
ship built in: :data:`~manorem_skills.packs.CORE` (always active),
:data:`~manorem_skills.packs.NETWORKS`, :data:`~manorem_skills.packs.GEOGRAPHY` and
:data:`~manorem_skills.packs.DATAVIZ`.

The usual path is one call and one hand-off::

    resolved = default_registry().resolve(scene.skills)
    report = validate_scene(scene, context=resolved.validation_context())
    prompt = vocabulary_prompt(resolved)

Both consumers read the same declarations, which is the point: the menu the model
is given and the rules the validator enforces are the same table, so they cannot
drift apart.

See :mod:`manorem_skills.protocol` for what a skill promises,
:mod:`manorem_skills.registry` for how a scene's request composes, and
:mod:`manorem_skills.packs` for the built-ins.
"""

from __future__ import annotations

from manorem_skills.pack import SkillPack, kinds, provide, refine
from manorem_skills.packs import BASE_PACK, BUILTIN_PACKS, CORE, DATAVIZ, GEOGRAPHY, NETWORKS
from manorem_skills.prompts import operation_lines, primitive_lines, vocabulary_prompt
from manorem_skills.protocol import (
    ExpandedStep,
    Expansion,
    ExpansionRule,
    LayoutRequest,
    LayoutSolver,
    PrimitiveDecl,
    SyntheticObject,
    VisualSkill,
)
from manorem_skills.registry import (
    ENTRY_POINT_GROUP,
    ResolvedSkills,
    SkillRegistry,
    default_registry,
)

__all__ = [
    "BASE_PACK",
    "BUILTIN_PACKS",
    "CORE",
    "DATAVIZ",
    "ENTRY_POINT_GROUP",
    "GEOGRAPHY",
    "NETWORKS",
    "ExpandedStep",
    "Expansion",
    "ExpansionRule",
    "LayoutRequest",
    "LayoutSolver",
    "PrimitiveDecl",
    "ResolvedSkills",
    "SkillPack",
    "SkillRegistry",
    "SyntheticObject",
    "VisualSkill",
    "default_registry",
    "kinds",
    "operation_lines",
    "primitive_lines",
    "provide",
    "refine",
    "vocabulary_prompt",
]
