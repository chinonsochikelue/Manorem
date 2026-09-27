"""The vocabulary section of the IR-generation prompt, built from the declarations.

The claim this module makes testable: *the model's menu and the validator's rules
cannot drift apart*. Both read the same :class:`~manorem_ir.OperationDecl` rows and
the same ``primitives`` mappings, so an operation the validator will reject cannot
appear on the menu, and an operation the model is never told about cannot be the
reason a scene fails. A hand-written prompt listing "flow, propagate, trace" would
be true on the day it was written and quietly wrong two commits later.

Scope is the vocabulary only -- which kinds exist, which operations exist, what
each takes. How to spell a ``TimeExpr``, what a ``Placement`` mode means, and the
JSON shape of a ``Scene`` are ``manorem_ir``'s to describe and ``packages/ai``'s to
assemble; a skill has no business restating them. Each pack's own
``prompt_fragment`` is appended verbatim after the generated tables, which is where
domain advice ("use `accumulate` when the growth is the point") belongs.
"""

from __future__ import annotations

from manorem_ir import ANY_KIND, ObjectKind, OperationDecl, ParamDecl, SemanticOp
from manorem_skills.protocol import PrimitiveDecl
from manorem_skills.registry import ResolvedSkills

__all__ = ["operation_lines", "primitive_lines", "vocabulary_prompt"]


def _render_default(*, value: float | str | bool | None) -> str:
    """JSON spelling, because the model is writing JSON.

    ``False`` rendered as Python's ``False`` invites ``"curved": False`` in a JSON
    document, which is a parse error rather than an interesting mistake. Keyword-only
    for the same reason ``_p`` is: a positional ``bool`` reads as a flag at the call
    site, and this one is the value being rendered.

    A whole number renders without its fraction. ``ParamDecl.default`` is typed
    ``float``, so a count of three arrives as ``3.0`` -- and ``count: number = 3.0``
    on the menu is an invitation to write ``"count": 2.5`` for a number of particles.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _render_param(param: ParamDecl) -> str:
    kind = "|".join(param.choices) if param.choices else param.type
    out = f"{param.name}: {kind}"
    if param.required:
        return f"{out} (required)"
    if param.default is not None:
        return f"{out} = {_render_default(value=param.default)}"
    return out


def _render_arity(decl: OperationDecl) -> str:
    if decl.min_targets == decl.max_targets:
        return f"{decl.min_targets} target" + ("" if decl.min_targets == 1 else "s")
    return f"{decl.min_targets}-{decl.max_targets} targets"


def primitive_lines(primitives: dict[ObjectKind, PrimitiveDecl]) -> list[str]:
    """One or two lines per object kind, sorted so the prompt is byte-stable."""
    lines: list[str] = []
    for kind in sorted(primitives, key=lambda k: k.value):
        decl = primitives[kind]
        lines.append(f"- `{kind.value}` -- {decl.summary}")
        if decl.prompt_hint:
            lines.append(f"  {decl.prompt_hint}")
    return lines


def operation_lines(
    operations: dict[SemanticOp, OperationDecl], allowed_kinds: frozenset[ObjectKind]
) -> list[str]:
    """One to three lines per operation, sorted so the prompt is byte-stable.

    Target kinds are intersected with what the enabled skills actually provide: an
    operation that also accepts ``globe`` is noise in a scene with no geography, and
    every token of noise is a token the model spends not writing the scene.
    """
    lines: list[str] = []
    for op in sorted(operations, key=lambda o: o.value):
        decl = operations[op]
        suffix = " [camera]" if decl.is_camera else ""
        lines.append(
            f"- `{op.value}` -- {decl.summary} "
            f"({_render_arity(decl)}, default {decl.default_duration}s){suffix}"
        )
        if decl.params:
            lines.append("  params: " + ", ".join(_render_param(p) for p in decl.params))
        if decl.allowed_kinds != ANY_KIND:
            usable = sorted(k.value for k in decl.allowed_kinds & allowed_kinds)
            lines.append(
                "  targets must be: " + (", ".join(usable) if usable else "(none enabled)")
            )
    return lines


def vocabulary_prompt(resolved: ResolvedSkills) -> str:
    """The complete vocabulary section for one scene's enabled skills."""
    enabled = ", ".join(f"`{skill_id}`" for skill_id in resolved.ids)
    parts: list[str] = [
        f"# Vocabulary\n\nEnabled skills: {enabled}.\n\n"
        "These are the only object kinds and operations available. Nothing outside "
        "these lists can be rendered; if the scene needs something absent, say so in "
        "the scene's `intent` rather than inventing a name.\n",
        "## Objects\n",
        *primitive_lines(dict(resolved.primitives)),
        "\n## Operations\n",
        *operation_lines(dict(resolved.operations), resolved.allowed_kinds),
    ]
    fragments = [skill.prompt_fragment.strip() for skill in resolved.skills]
    written = [fragment for fragment in fragments if fragment]
    if written:
        parts.append("\n## Guidance\n")
        parts.extend(f"{fragment}\n" for fragment in written)
    return "\n".join(parts).rstrip() + "\n"
