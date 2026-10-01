"""The ratchet on the diagnostic vocabulary itself.

Every other module in this directory tests *behaviour*. This one tests the
*rules about the rules*, because two of them are load-bearing and neither is
enforceable by reading any single test:

* **"one test per diagnostic code"** is only a rule if adding a code without a
  test fails the build. Otherwise the next ``IR216`` ships untested and the gap
  is invisible -- the suite still passes, it just no longer covers what it claims.
* **``SEMANTIC_ERROR_CODES`` must be exactly the IR2xx block.** This is where the
  autofix guardrail actually lives. A new referential error omitted from that
  frozenset becomes silently autofixable, and autofix would then be free to
  "clean up" a dangling reference -- discarding authorial intent and hiding a
  planner defect behind a plausible-looking render. The guardrail is one line of
  set arithmetic away from being lost, so it is asserted rather than trusted.

The sweep is textual: it proves a code is *named* in a test module, not that the
naming is a meaningful assertion. That is a deliberate limit. A weak ratchet that
catches the forgotten code is worth more than no ratchet, and nothing here should
be read as evidence that a code's behaviour is well covered.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from manorem_core import Code, Diagnostic, Severity
from manorem_core.diagnostics import SEMANTIC_ERROR_CODES

#: Namespace prefix -> the leading digit of its numbering block. The prefix is how
#: the repair agent routes a finding, so a code numbered outside its own block is
#: a code that will be routed somewhere its subsystem cannot act on.
_NAMESPACE_BLOCKS: dict[str, frozenset[str]] = {
    "IR": frozenset({"1", "2", "3"}),
    "CMP": frozenset({"4"}),
    "RND": frozenset({"5"}),
    "VQA": frozenset({"6"}),
    "MUX": frozenset({"7"}),
    "RES": frozenset({"8"}),
    "AUD": frozenset({"9"}),
}

_CODE_SHAPE = re.compile(r"^(IR|CMP|RND|VQA|MUX|RES|AUD)(\d)\d\d_[A-Z][A-Z0-9_]*$")

#: Codes this directory is responsible for. The later namespaces belong to
#: packages that do not exist yet; ``test_every_namespace_is_accounted_for``
#: is what keeps them from being forgotten rather than merely unrequired.
_IR_PREFIXES = ("IR1", "IR2", "IR3")


def _ir_codes() -> list[Code]:
    return [code for code in Code if code.value.startswith(_IR_PREFIXES)]


def _test_sources() -> dict[Path, str]:
    """Every test module in this directory except this one.

    Excluding self is what keeps the ratchet honest: a code mentioned only in the
    coverage test's own bookkeeping would otherwise satisfy the requirement it is
    supposed to impose.
    """
    here = Path(__file__).resolve()
    return {
        path: path.read_text(encoding="utf-8")
        for path in sorted(here.parent.glob("test_*.py"))
        if path.resolve() != here
    }


class TestEveryCodeIsExercised:
    """The "one test per diagnostic code" rule, made checkable."""

    def test_the_sweep_finds_the_sibling_modules(self) -> None:
        # Guards the guard: a glob that silently matched nothing would turn every
        # assertion below into a vacuous pass.
        sources = _test_sources()

        assert len(sources) >= 8
        assert not any(path.name == Path(__file__).name for path in sources)

    @pytest.mark.parametrize("code", _ir_codes(), ids=lambda c: c.value)
    def test_each_ir_code_is_named_by_some_test(self, code: Code) -> None:
        # Parametrized so a missing code names itself in the failure line, rather
        # than one opaque assertion listing everything at once.
        assert any(code.value in text for text in _test_sources().values())

    def test_the_ir_namespace_is_fully_enumerated(self) -> None:
        # Not a magic total to keep in sync: the assertion is that the three blocks
        # partition the namespace with nothing stranded between them.
        by_block = {
            prefix: [c for c in _ir_codes() if c.value.startswith(prefix)]
            for prefix in _IR_PREFIXES
        }

        assert sum(len(v) for v in by_block.values()) == len(_ir_codes())
        assert all(by_block[prefix] for prefix in _IR_PREFIXES)


class TestTheAutofixGuardrail:
    """Where "autofix never drops semantic content" is actually enforced."""

    def test_the_semantic_set_is_exactly_the_referential_block(self) -> None:
        # The whole guardrail in one assertion. An IR2xx code left out of the
        # frozenset is a referential error autofix may quietly repair.
        referential = frozenset(code for code in Code if code.value.startswith("IR2"))

        assert referential == SEMANTIC_ERROR_CODES

    def test_no_structural_or_pacing_code_is_marked_semantic(self) -> None:
        # The other direction: over-claiming would route a mechanically fixable
        # normalization problem to the bounded repair agent and burn an attempt.
        assert not any(code.value.startswith(("IR1", "IR3")) for code in SEMANTIC_ERROR_CODES)

    @pytest.mark.parametrize("code", sorted(SEMANTIC_ERROR_CODES), ids=lambda c: c.value)
    def test_a_semantic_code_is_never_autofixable(self, code: Code) -> None:
        # Asserted at WARNING severity deliberately: the code alone must disqualify
        # it, so downgrading the severity cannot smuggle it past autofix.
        warning = Diagnostic(code=code, severity=Severity.WARNING, message="x")

        assert not warning.autofixable

    def test_severity_alone_also_disqualifies(self) -> None:
        # A non-semantic ERROR is still not autofixable -- ``autofixable`` is the
        # conjunction of both conditions, not either one.
        error = Diagnostic(code=Code.IR101_SCHEMA_INVALID, severity=Severity.ERROR, message="x")

        assert not error.autofixable
        assert Diagnostic(
            code=Code.IR101_SCHEMA_INVALID, severity=Severity.WARNING, message="x"
        ).autofixable


class TestCodeNamesAreStable:
    """A code is a wire value, not just a Python symbol."""

    @pytest.mark.parametrize("code", list(Code), ids=lambda c: c.value)
    def test_the_symbol_and_the_serialized_value_agree(self, code: Code) -> None:
        # Diagnostics cross a JSON boundary into the repair agent, the inspector
        # and the logs. If ``Code.IR201_UNKNOWN_OBJECT_REF`` did not serialize to
        # that exact string, every consumer table would key on something else.
        assert code.value == code.name

    @pytest.mark.parametrize("code", list(Code), ids=lambda c: c.value)
    def test_every_code_is_shaped_like_a_code(self, code: Code) -> None:
        assert _CODE_SHAPE.match(code.value) is not None

    @pytest.mark.parametrize("code", list(Code), ids=lambda c: c.value)
    def test_every_code_sits_inside_its_namespace_block(self, code: Code) -> None:
        match = _CODE_SHAPE.match(code.value)

        assert match is not None
        prefix, block = match.group(1), match.group(2)
        assert block in _NAMESPACE_BLOCKS[prefix]

    def test_numbers_are_unique_across_the_whole_vocabulary(self) -> None:
        # Two codes sharing a number would be indistinguishable in a log line even
        # though they are distinct enum members.
        numbers = [code.value.split("_")[0] for code in Code]

        assert sorted(numbers) == sorted(set(numbers))

    def test_every_namespace_is_accounted_for(self) -> None:
        # A typo'd namespace -- ``IR4xx``, say -- would escape both this directory's
        # requirement and whatever requirement its real subsystem later imposes.
        prefixes = {m.group(1) for code in Code if (m := _CODE_SHAPE.match(code.value))}

        assert prefixes == set(_NAMESPACE_BLOCKS)
