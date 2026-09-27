"""Each agent assembles a prompt, asks for its schema, and returns the value.

The agents share one base, so these tests check the wiring per agent rather than
the model: the stub asserts it was asked for the agent's declared output schema,
and returns a prepared instance that the agent must hand back untouched.
"""

from __future__ import annotations

from pydantic import BaseModel

from manorem_ai import (
    IRGeneratorAgent,
    Prompt,
    ResearchAgent,
    ScriptAgent,
    StoryAgent,
    VisualPlannerAgent,
)
from manorem_ai.agents.models import Script, StoryOutline, VisualPlan
from manorem_ai.provider import Completion
from manorem_ai.research import ResearchBrief
from manorem_ir import Scene
from tests.support.ai_builders import brief_citing, gps_document, outline, plan, script
from tests.support.ir_builders import valid_scene


class _RecordingStub:
    """A stub that remembers the last schema it was asked for."""

    name = "recording"

    def __init__(self, value: BaseModel) -> None:
        self._value = value
        self.schema_seen: type[BaseModel] | None = None

    def structured[T: BaseModel](
        self,
        *,
        prompt: Prompt,
        schema: type[T],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> Completion[T]:
        self.schema_seen = schema
        assert isinstance(self._value, schema)
        return Completion(value=self._value, model=model)


def test_research_agent_returns_a_brief() -> None:
    stub = _RecordingStub(brief_citing())
    result = ResearchAgent(stub, model="m").run("idea", (gps_document(),))
    assert stub.schema_seen is ResearchBrief
    assert isinstance(result.value, ResearchBrief)


def test_story_agent_returns_an_outline() -> None:
    stub = _RecordingStub(outline())
    result = StoryAgent(stub, model="m").run(brief_citing())
    assert stub.schema_seen is StoryOutline
    assert isinstance(result.value, StoryOutline)


def test_script_agent_returns_a_script() -> None:
    stub = _RecordingStub(script())
    result = ScriptAgent(stub, model="m").run(outline())
    assert stub.schema_seen is Script
    assert isinstance(result.value, Script)


def test_visual_planner_returns_a_plan() -> None:
    stub = _RecordingStub(plan())
    beat = outline().beats[0]
    result = VisualPlannerAgent(stub, model="m").run(beat, script().segments[0], vocabulary="v")
    assert stub.schema_seen is VisualPlan
    assert isinstance(result.value, VisualPlan)


def test_ir_generator_returns_a_scene() -> None:
    stub = _RecordingStub(valid_scene())
    result = IRGeneratorAgent(stub, model="m").run(plan(), script().segments[0], vocabulary="v")
    assert stub.schema_seen is Scene
    assert isinstance(result.value, Scene)
