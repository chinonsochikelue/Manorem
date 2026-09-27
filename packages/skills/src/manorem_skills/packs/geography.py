"""The ``geography`` pack: places, and the frames that hold them.

Two kinds and one operation, which is the whole pack. A ``map`` or ``globe`` is a
*coordinate frame* as much as a drawing -- markers on it are placed in map space,
not stage space -- and ``trace`` is how a route across that frame gets drawn.

No constraints in M1, deliberately. Geography's real rules are about coordinate
frames (does this marker's lat/lon fall inside the projected region; do two frames
in one scene stay distinguishable), and answering them needs the ``map`` layout
solver that pass P3 does not have yet. A predicate written now would either
restate what ``IR215`` already checks or guess at a projection that does not
exist -- so the pack declares its vocabulary and waits for P3.
"""

from __future__ import annotations

from manorem_ir import ObjectKind, SemanticOp
from manorem_skills.pack import SkillPack, kinds, provide
from manorem_skills.protocol import PrimitiveDecl

_PROMPT = """\
The `geography` vocabulary places things on the world.

Objects: `map` for a flat projection of a region, `globe` for the sphere when
curvature or the whole planet is the point.

Operations: `trace` to draw a route across the frame.

Markers and labels are `core` objects (`dot`, `icon`, `text`) anchored to the map
rather than a separate kind, so the same marker vocabulary works on a globe, on a
diagram, or on bare stage.
"""

GEOGRAPHY = SkillPack(
    id="geography",
    version="1.0",
    summary="Maps, globes, and routes across them.",
    primitives=kinds(
        PrimitiveDecl(
            kind=ObjectKind.MAP,
            summary="A flat projection of a region, acting as a coordinate frame.",
            prompt_hint="Name the region; anchor markers to the map rather than to the stage.",
        ),
        PrimitiveDecl(
            kind=ObjectKind.GLOBE,
            summary="The sphere, for when curvature or planetary scale matters.",
        ),
    ),
    operations=provide(SemanticOp.TRACE),
    prompt_fragment=_PROMPT,
)
