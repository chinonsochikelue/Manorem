"""The AI pipeline: idea to validated Visual IR to a captioned video.

This package holds everything model-facing and everything that guards it. The
:class:`~manorem_ai.pipeline.Pipeline` chains six typed agents -- research, story,
script, visual planning, IR generation, repair -- behind one
:class:`~manorem_ai.provider.LLMProvider` seam, with offline
:class:`~manorem_ai.cassette.StubProvider` / :class:`~manorem_ai.cassette.CassetteProvider`
backends for deterministic tests and a live :class:`~manorem_ai.gemini.GeminiProvider`
(its SDK imported lazily, so this package imports with no client installed).

Three guardrails live here as types, not conventions:
:class:`~manorem_ai.research.ProvenanceValidator` proves a citation was retrieved
(not that it supports the claim); :func:`~manorem_ai.patch.apply_scene_patch` lets
repair fix references but never add or drop an entity; and
:class:`~manorem_ai.quality.NoopVisualQA` returns ``None`` for *not assessed*, kept
distinct from *assessed and fine*.
"""

from __future__ import annotations

from manorem_ai.agents import (
    Agent,
    IRGeneratorAgent,
    RepairAgent,
    ResearchAgent,
    ScriptAgent,
    StoryAgent,
    VisualPlannerAgent,
    load_prompt,
    render_input,
)
from manorem_ai.agents.models import Beat, Script, StoryOutline, VisualPlan
from manorem_ai.anthropic import AnthropicProvider
from manorem_ai.arcs import StoryArc, arc_menu, get_arc
from manorem_ai.cassette import CassetteProvider, StubProvider
from manorem_ai.gemini import GeminiProvider
from manorem_ai.keypool import KeyPoolProvider
from manorem_ai.openai import OpenAIProvider
from manorem_ai.pacing import PacingReport, pace_script
from manorem_ai.patch import JsonPatch, PatchError, PatchOp, apply_patch, apply_scene_patch
from manorem_ai.pipeline import Pipeline, PipelineError, PipelineResult
from manorem_ai.provider import (
    Completion,
    LLMProvider,
    OutputValidationError,
    Prompt,
    PromptExample,
    ProviderError,
    RateLimitError,
    Usage,
    prompt_cache_key,
    validation_feedback,
)
from manorem_ai.quality import NoopVisualQA, VisualQA
from manorem_ai.research import (
    Claim,
    Document,
    Entity,
    FixtureResearchProvider,
    ProvenanceValidator,
    ResearchBrief,
    ResearchProvider,
    SourceRef,
    VisualCandidate,
)
from manorem_ai.schema_shim import to_gemini_schema

__all__ = [
    "Agent",
    "AnthropicProvider",
    "Beat",
    "CassetteProvider",
    "Claim",
    "Completion",
    "Document",
    "Entity",
    "FixtureResearchProvider",
    "GeminiProvider",
    "IRGeneratorAgent",
    "JsonPatch",
    "KeyPoolProvider",
    "LLMProvider",
    "NoopVisualQA",
    "OpenAIProvider",
    "OutputValidationError",
    "PacingReport",
    "PatchError",
    "PatchOp",
    "Pipeline",
    "PipelineError",
    "PipelineResult",
    "Prompt",
    "PromptExample",
    "ProvenanceValidator",
    "ProviderError",
    "RateLimitError",
    "RepairAgent",
    "ResearchAgent",
    "ResearchBrief",
    "ResearchProvider",
    "Script",
    "ScriptAgent",
    "SourceRef",
    "StoryAgent",
    "StoryArc",
    "StoryOutline",
    "StubProvider",
    "Usage",
    "VisualCandidate",
    "VisualPlan",
    "VisualPlannerAgent",
    "VisualQA",
    "apply_patch",
    "apply_scene_patch",
    "arc_menu",
    "get_arc",
    "load_prompt",
    "pace_script",
    "prompt_cache_key",
    "render_input",
    "to_gemini_schema",
    "validation_feedback",
]
