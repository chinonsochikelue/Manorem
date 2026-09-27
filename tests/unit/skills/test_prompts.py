"""The generated vocabulary prompt, and the drift it is there to prevent.

The claim is that the model's menu and the validator's rules cannot diverge, and the
tests that matter here are the two that would catch a divergence: every operation in
the resolved registry is named in the prompt, and no operation outside it is. Both
run over the *enum values*, so an operation added to a pack without a word of prose
fails, and a stale mention of one the scene cannot use fails too.

Byte-stability is tested for the same reason the compiler's goldens are: a prompt
that reorders between runs makes an LLM cassette key unstable, and every replayed
test would start missing.
"""

from __future__ import annotations

import re

from manorem_ir import ANY_KIND, ObjectKind, SemanticOp
from manorem_skills import default_registry, operation_lines, primitive_lines, vocabulary_prompt

#: Backticked lowercase tokens, which is how the prompt spells every name.
_TOKEN = re.compile(r"`([a-z][a-z0-9_]*)`")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text))


def _prompt(*skills: str) -> str:
    return vocabulary_prompt(default_registry().resolve(list(skills)))


class TestTheMenuMatchesTheRules:
    def test_every_enabled_operation_is_named(self) -> None:
        resolved = default_registry().resolve(["networks"])
        named = _tokens(vocabulary_prompt(resolved))
        missing = sorted(op.value for op in resolved.registry.known_ops() if op.value not in named)
        assert not missing, f"operations the model is never told about: {missing}"

    def test_no_disabled_operation_is_named(self) -> None:
        resolved = default_registry().resolve(["networks"])
        named = _tokens(vocabulary_prompt(resolved))
        enabled = {op.value for op in resolved.registry.known_ops()}
        offered = {op.value for op in SemanticOp if op.value in named}
        assert offered <= enabled, f"offered but unusable: {sorted(offered - enabled)}"

    def test_every_enabled_kind_is_named(self) -> None:
        resolved = default_registry().resolve(["geography"])
        named = _tokens(vocabulary_prompt(resolved))
        missing = sorted(k.value for k in resolved.allowed_kinds if k.value not in named)
        assert not missing, f"kinds the model is never told about: {missing}"

    def test_no_disabled_kind_is_named(self) -> None:
        resolved = default_registry().resolve(["geography"])
        named = _tokens(vocabulary_prompt(resolved))
        allowed = {k.value for k in resolved.allowed_kinds}
        offered = {k.value for k in ObjectKind if k.value in named}
        assert offered <= allowed, f"offered but unusable: {sorted(offered - allowed)}"

    def test_enabling_everything_offers_everything(self) -> None:
        named = _tokens(_prompt("networks", "geography", "dataviz"))
        assert {op.value for op in SemanticOp} <= named
        assert {kind.value for kind in ObjectKind} <= named


class TestThePromptIsStable:
    def test_repeated_builds_are_byte_identical(self) -> None:
        assert _prompt("networks") == _prompt("networks")

    def test_kinds_and_operations_are_sorted(self) -> None:
        resolved = default_registry().resolve(["dataviz"])
        kinds = [
            line for line in primitive_lines(dict(resolved.primitives)) if line.startswith("- ")
        ]
        assert kinds == sorted(kinds)
        ops = [
            line
            for line in operation_lines(dict(resolved.operations), resolved.allowed_kinds)
            if line.startswith("- ")
        ]
        assert ops == sorted(ops)

    def test_the_enabled_skills_are_listed_in_composition_order(self) -> None:
        assert "Enabled skills: `core`, `networks`, `dataviz`." in _prompt("networks", "dataviz")


class TestWhatEachLineTells:
    def test_a_required_param_is_marked(self) -> None:
        lines = operation_lines(
            {
                SemanticOp.ACCUMULATE: default_registry()
                .resolve(["dataviz"])
                .operations[SemanticOp.ACCUMULATE]
            },
            frozenset(ObjectKind),
        )
        assert any("to: number (required)" in line for line in lines)

    def test_a_boolean_default_is_spelled_for_json(self) -> None:
        # ``"curved": False`` is a JSON parse error, not an interesting mistake.
        text = _prompt("networks")
        assert "curved: bool = false" in text
        assert "False" not in text

    def test_a_whole_number_default_drops_its_fraction(self) -> None:
        # ``ParamDecl.default`` is typed float, so a count of three arrives as 3.0 --
        # and ``count = 3.0`` on the menu invites ``"count": 2.5`` for a particle
        # count. A genuine fraction must survive, which is why both are asserted.
        assert "count: number = 3, stagger: number = 0.2" in _prompt("networks")

    def test_enum_choices_replace_the_type(self) -> None:
        assert "style: create|write|fade|grow|draw = create" in _prompt()

    def test_camera_operations_are_flagged(self) -> None:
        text = _prompt()
        assert "`zoom_to`" in text
        assert "[camera]" in text.split("`zoom_to`")[1].split("\n")[0]

    def test_arity_and_default_duration_appear(self) -> None:
        assert "(1-50 targets, default 1.0s)" in _prompt()
        assert "(2 targets, default 1.5s)" in _prompt("networks")

    def test_an_unrestricted_operation_lists_no_target_kinds(self) -> None:
        # ``show`` accepts everything, so naming 21 kinds under it would be noise --
        # and every token of noise is one the model spends not writing the scene.
        resolved = default_registry().resolve()
        assert resolved.operations[SemanticOp.SHOW].allowed_kinds == ANY_KIND
        show_block = _prompt().split("- `show`")[1].split("- `")[0]
        assert "targets must be" not in show_block

    def test_a_restricted_operation_lists_only_enabled_kinds(self) -> None:
        block = _prompt("networks").split("- `flow`")[1].split("- `")[0]
        assert "targets must be:" in block
        assert "map" not in block  # geography is not enabled

    def test_each_pack_contributes_its_guidance(self) -> None:
        text = _prompt("networks", "dataviz")
        assert "## Guidance" in text
        assert "The `core` vocabulary is always available." in text
        assert "The `networks` vocabulary describes things joined to other things." in text
        assert "The `dataviz` vocabulary shows quantities." in text

    def test_a_prompt_hint_follows_its_kind(self) -> None:
        lines = primitive_lines(dict(default_registry().resolve().primitives))
        index = lines.index("- `text` -- A line or short block of words.")
        assert lines[index + 1].strip().startswith("Use a style role")

    def test_the_prompt_ends_with_exactly_one_newline(self) -> None:
        text = _prompt("networks")
        assert text.endswith("\n")
        assert not text.endswith("\n\n")
