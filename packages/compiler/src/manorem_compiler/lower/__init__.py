"""P7 lowering: the last semantic decisions, split by what they decide.

:mod:`~manorem_compiler.lower.mobjects` turns semantic object kinds into concrete
drawables and resolves colours; :mod:`~manorem_compiler.lower.anims` turns a single
step's intent into one animation; :mod:`~manorem_compiler.lower.tracks` lanes those
animations and assembles the finished scene plan. The pass module wires them.
"""

from __future__ import annotations

from manorem_compiler.lower.anims import anim_for
from manorem_compiler.lower.mobjects import lower_mobjects
from manorem_compiler.lower.tracks import build_scene_plan

__all__ = ["anim_for", "build_scene_plan", "lower_mobjects"]
