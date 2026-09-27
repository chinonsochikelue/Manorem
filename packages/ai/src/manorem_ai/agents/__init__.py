"""The pipeline's agents: one module each, uniform typed I/O.

Every agent extends :class:`~manorem_ai.agents.base.Agent`, loads its own prompt
file, and turns a typed input into a validated :class:`~manorem_ai.provider.Completion`
of its output schema. Importing them here keeps the pipeline's import list flat and
gives the package one obvious place to see the whole cast:

* :class:`ResearchAgent` -- idea + retrieved docs -> ``ResearchBrief``
* :class:`StoryAgent` -- brief -> ``StoryOutline`` (arc chosen and justified)
* :class:`ScriptAgent` -- outline -> ``Script`` (timings added later, deterministically)
* :class:`VisualPlannerAgent` -- beat + segment -> ``VisualPlan``
* :class:`IRGeneratorAgent` -- plan -> one validated ``Scene``
* :class:`RepairAgent` -- diagnostics + scene -> ``JsonPatch``
"""

from __future__ import annotations

from manorem_ai.agents.base import Agent, load_prompt, render_input
from manorem_ai.agents.ir_generator import IRGeneratorAgent
from manorem_ai.agents.models import Beat, Script, StoryOutline, VisualPlan
from manorem_ai.agents.repair import RepairAgent
from manorem_ai.agents.research import ResearchAgent
from manorem_ai.agents.script import ScriptAgent
from manorem_ai.agents.story import StoryAgent
from manorem_ai.agents.visual_planner import VisualPlannerAgent

__all__ = [
    "Agent",
    "Beat",
    "IRGeneratorAgent",
    "RepairAgent",
    "ResearchAgent",
    "Script",
    "ScriptAgent",
    "StoryAgent",
    "StoryOutline",
    "VisualPlan",
    "VisualPlannerAgent",
    "load_prompt",
    "render_input",
]
