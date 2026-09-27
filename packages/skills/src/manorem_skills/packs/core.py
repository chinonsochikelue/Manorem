"""The ``core`` pack: what every scene can assume exists.

Always active, whatever ``Scene.skills`` says. A scene that lists only
``networks`` still needs ``show`` before anything can be connected, so the
registry prepends this pack rather than trusting authors to remember it.

The kinds here are the shape-and-text vocabulary -- the things an explainer draws
when the subject has no domain of its own. The operations are the ones whose
meaning does not change with the subject: appearing, disappearing, being pointed
at, being turned into something else, and moving the camera.
"""

from __future__ import annotations

from manorem_ir import ObjectKind, SemanticOp
from manorem_skills.pack import SkillPack, kinds, provide
from manorem_skills.protocol import PrimitiveDecl

_PROMPT = """\
The `core` vocabulary is always available.

Objects: `text` for words on screen, `math` for LaTeX, `circle`/`rectangle`/
`polygon`/`line`/`dot` for shapes, `arrow` to point from one thing to another,
`icon`/`image`/`svg` for supplied assets, `group` to move several objects as one.

Operations: `show` and `hide` to bring objects on and off; `highlight` to draw
attention without moving the camera; `focus`, `zoom_to` and `pan_to` to move the
camera; `transform` and `morph` to turn one object into another; `reveal` to
uncover progressively; `split` and `merge` to divide and combine; `compare` to
place objects side by side.

Every object must be shown before any other operation targets it.
"""

CORE = SkillPack(
    id="core",
    version="1.0",
    summary="Text, shapes, arrows and the operations whose meaning never changes.",
    primitives=kinds(
        PrimitiveDecl(
            kind=ObjectKind.TEXT,
            summary="A line or short block of words.",
            prompt_hint="Use a style role (title, heading, body, caption), never a font size.",
        ),
        PrimitiveDecl(
            kind=ObjectKind.MATH,
            summary="A LaTeX expression.",
            prompt_hint="For formulae only; prose belongs in `text`.",
        ),
        PrimitiveDecl(kind=ObjectKind.CIRCLE, summary="A circle, filled or outlined."),
        PrimitiveDecl(kind=ObjectKind.RECTANGLE, summary="A rectangle, optionally rounded."),
        PrimitiveDecl(kind=ObjectKind.POLYGON, summary="A closed shape from three or more points."),
        PrimitiveDecl(
            kind=ObjectKind.LINE,
            summary="A straight or dashed segment between two stage points.",
        ),
        PrimitiveDecl(
            kind=ObjectKind.DOT,
            summary="A small marker: a position, a particle, a data point.",
        ),
        PrimitiveDecl(
            kind=ObjectKind.ARROW,
            summary="A directed connector between two objects or points.",
            prompt_hint="Prefer object ids as endpoints so layout can move both ends.",
        ),
        PrimitiveDecl(kind=ObjectKind.ICON, summary="A named glyph from the icon set."),
        PrimitiveDecl(kind=ObjectKind.IMAGE, summary="A raster asset supplied with the project."),
        PrimitiveDecl(kind=ObjectKind.SVG, summary="A vector asset supplied with the project."),
        PrimitiveDecl(
            kind=ObjectKind.GROUP,
            summary="Several objects addressed as one.",
            prompt_hint="Members must be declared objects; a group cannot contain itself.",
        ),
    ),
    operations=provide(
        SemanticOp.SHOW,
        SemanticOp.HIDE,
        SemanticOp.HIGHLIGHT,
        SemanticOp.FOCUS,
        SemanticOp.ZOOM_TO,
        SemanticOp.PAN_TO,
        SemanticOp.TRANSFORM,
        SemanticOp.MORPH,
        SemanticOp.REVEAL,
        SemanticOp.SPLIT,
        SemanticOp.MERGE,
        SemanticOp.COMPARE,
    ),
    prompt_fragment=_PROMPT,
)
