"""Diagnostics are the contract between validation, compilation and repair.

The critical property under test is that ``autofixable`` is *derived*: no caller
can mark semantic damage as machine-repairable, because that would let autofix
silently drop authorial intent.
"""

from __future__ import annotations

import pytest

from manorem_core import (
    SEMANTIC_ERROR_CODES,
    Code,
    Diagnostic,
    DiagnosticBag,
    Severity,
    pointer,
)


class TestPointer:
    def test_builds_rfc6901_path(self) -> None:
        assert pointer("scenes", 0, "objects", 2) == "/scenes/0/objects/2"

    def test_empty_is_document_root(self) -> None:
        assert pointer() == ""

    @pytest.mark.parametrize(
        ("part", "expected"),
        [("a/b", "/a~1b"), ("a~b", "/a~0b"), ("a~/b", "/a~0~1b")],
    )
    def test_escapes_reserved_characters(self, part: str, expected: str) -> None:
        assert pointer(part) == expected


class TestAutofixableIsDerived:
    """The guardrail: autofix may never touch semantic content."""

    @pytest.mark.parametrize("code", sorted(SEMANTIC_ERROR_CODES))
    def test_semantic_codes_are_never_autofixable(self, code: Code) -> None:
        # Even constructed at the lowest severity, semantic damage stays off-limits.
        for severity in Severity:
            d = Diagnostic(code=code, severity=severity, message="x")
            assert d.autofixable is False, f"{code} must escalate to the repair agent"

    def test_semantic_set_covers_every_ir2xx_code(self) -> None:
        # IR2xx *is* the referential/semantic namespace; a new code added there
        # must be added to the guardrail set too, or autofix could eat it.
        ir2xx = {c for c in Code if c.value.startswith("IR2")}
        assert ir2xx == SEMANTIC_ERROR_CODES

    def test_non_semantic_warning_is_autofixable(self) -> None:
        d = Diagnostic(code=Code.IR301_NARRATION_OVERFLOW, severity=Severity.WARNING, message="x")
        assert d.autofixable is True

    def test_non_semantic_error_is_not_autofixable(self) -> None:
        # Severity ERROR alone is enough to require attention.
        d = Diagnostic(code=Code.CMP401_LAYOUT_UNSOLVABLE, severity=Severity.ERROR, message="x")
        assert d.autofixable is False

    def test_diagnostic_is_immutable(self) -> None:
        d = Diagnostic(code=Code.IR104_EMPTY_SCENE, severity=Severity.ERROR, message="x")
        with pytest.raises(ValueError, match="frozen"):
            d.severity = Severity.INFO


class TestCodeNamespaces:
    @pytest.mark.parametrize("prefix", ["IR1", "IR2", "IR3", "CMP4", "RND5", "VQA6"])
    def test_namespace_is_populated(self, prefix: str) -> None:
        assert [c for c in Code if c.value.startswith(prefix)]

    def test_code_name_matches_value(self) -> None:
        # Keeps grep-ability: the symbol and the wire value never diverge.
        for code in Code:
            assert code.name == code.value


class TestDiagnosticBag:
    def test_collects_and_partitions_by_severity(self) -> None:
        bag = DiagnosticBag()
        bag.add(Code.IR201_UNKNOWN_OBJECT_REF, "missing satellite_4", object_id="satellite_4")
        bag.warn(Code.IR302_DEAD_AIR, "4s of nothing")

        assert bag.has_errors
        assert len(bag) == 2
        assert len(bag.errors) == 1
        assert len(bag.warnings) == 1
        assert bag.codes() == {Code.IR201_UNKNOWN_OBJECT_REF, Code.IR302_DEAD_AIR}

    def test_empty_bag_has_no_errors(self) -> None:
        assert not DiagnosticBag().has_errors

    def test_sorted_puts_errors_first(self) -> None:
        bag = DiagnosticBag()
        bag.warn(Code.IR302_DEAD_AIR, "w")
        bag.add(Code.IR201_UNKNOWN_OBJECT_REF, "e")

        assert [d.severity for d in bag.sorted().items] == [Severity.ERROR, Severity.WARNING]

    def test_extend_accepts_bag_or_list(self) -> None:
        a, b = DiagnosticBag(), DiagnosticBag()
        a.add(Code.IR104_EMPTY_SCENE, "1")
        b.add(Code.IR106_NO_SCENES, "2")
        a.extend(b)
        a.extend([Diagnostic(code=Code.IR103_INVALID_ID, severity=Severity.INFO, message="3")])

        assert len(a) == 3

    def test_str_is_human_readable(self) -> None:
        d = Diagnostic(
            code=Code.IR201_UNKNOWN_OBJECT_REF,
            severity=Severity.ERROR,
            message="unknown object 'satellite_4'",
            pointer="/scenes/2/timeline/1",
            scene_id="gps_trilateration",
        )
        rendered = str(d)

        assert "IR201_UNKNOWN_OBJECT_REF" in rendered
        assert "gps_trilateration" in rendered
        assert "/scenes/2/timeline/1" in rendered
