"""The zero-diagnostics baseline.

Every other validation test asserts that something *is* reported. This one asserts
the opposite, which is the harder half of the contract: a validator that flags an
ordinary well-formed scene is worse than useless, because the repair loop will
spend its two bounded attempts rewriting IR that was already correct.

If a newly added check fires here, the check is wrong -- not the fixture.
"""

from __future__ import annotations

import pytest

from manorem_ir import (
    Aspect,
    FormatSpec,
    ValidationContext,
    ValidationPolicy,
    validate_project,
    validate_scene,
)
from tests.support.diag import rendered
from tests.support.ir_builders import valid_project, valid_scene


class TestValidBaseline:
    def test_scene_is_clean(self) -> None:
        assert rendered(validate_scene(valid_scene())) == []

    def test_project_is_clean(self) -> None:
        assert rendered(validate_project(valid_project())) == []

    def test_clean_under_strict_lints(self) -> None:
        # Promotion changes severity, never the set of findings.
        ctx = ValidationContext(policy=ValidationPolicy(strict_lints=True))
        assert rendered(validate_scene(valid_scene(), ctx)) == []

    @pytest.mark.parametrize("fps", [15, 24, 30, 60])
    def test_clean_at_every_frame_rate(self, fps: int) -> None:
        # IR105 is format-dependent; the baseline must survive the slowest rate.
        assert rendered(validate_scene(valid_scene(), ValidationContext(fps=fps))) == []

    @pytest.mark.parametrize("aspect", list(Aspect))
    def test_clean_in_every_aspect(self, aspect: Aspect) -> None:
        # Authored IR carries no aspect assumptions, so retargeting cannot break it.
        project = valid_project().with_format(FormatSpec.for_quality(aspect=aspect))
        assert rendered(validate_project(project)) == []
