"""The built-in skill packs.

Four packs whose vocabularies partition the two closed enums exactly: every
:class:`~manorem_ir.ObjectKind` is provided by exactly one pack, and every
:class:`~manorem_ir.SemanticOp` by at least one. Tests assert both, so adding an
enum member without a pack to provide it fails the build rather than producing a
kind no scene can legally use.

``trace`` is the single deliberate overlap -- ``networks`` needs it for a trail
behind a moving dot and ``geography`` for a route across a map. Both take it from
the base table unchanged via :func:`~manorem_skills.pack.provide`, so which pack
"wins" during composition cannot matter.
"""

from __future__ import annotations

from manorem_skills.pack import SkillPack
from manorem_skills.packs.core import CORE
from manorem_skills.packs.dataviz import DATAVIZ
from manorem_skills.packs.geography import GEOGRAPHY
from manorem_skills.packs.networks import NETWORKS

#: The pack that is always active, whatever a scene requests.
BASE_PACK: SkillPack = CORE

#: Every pack shipped with manorem, in a stable order.
BUILTIN_PACKS: tuple[SkillPack, ...] = (CORE, NETWORKS, GEOGRAPHY, DATAVIZ)

__all__ = [
    "BASE_PACK",
    "BUILTIN_PACKS",
    "CORE",
    "DATAVIZ",
    "GEOGRAPHY",
    "NETWORKS",
]
