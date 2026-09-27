"""Stage space arithmetic: the geometry the layout engine and two lints stand on.

Every number here is aspect-independent by construction -- the mapping to world
units is compiler pass P6's job and appears nowhere in this module. What these
tests pin is the *edge behaviour*, because two validators read it in opposite
directions and both readings have to stay true:

* ``intersects`` excludes a shared edge, so boxes laid side by side are a tight
  layout rather than an IR304 overlap finding.
* ``contains`` includes its edges, so content filling the safe area exactly is
  legal rather than an IR305 off-stage finding.

Getting either backwards produces a validator that fires on good layouts and a
repair loop that dutifully "fixes" them.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from manorem_ir import ORIGIN, SAFE_AREA, StageBounds, StagePoint, StageSize, union_all

_UNIT = StageBounds(min_x=0.0, min_y=0.0, max_x=1.0, max_y=1.0)


class TestStagePoint:
    """The authored coordinate type: only points a layout could mean."""

    def test_the_origin_is_frame_center(self) -> None:
        assert ORIGIN.as_tuple() == (0.0, 0.0)

    def test_addition_and_scaling(self) -> None:
        point = StagePoint(x=0.25, y=-0.5)

        assert (point + StagePoint(x=0.5, y=0.5)).as_tuple() == pytest.approx((0.75, 0.0))
        assert point.scaled(2.0).as_tuple() == pytest.approx((0.5, -1.0))

    def test_distance(self) -> None:
        assert StagePoint(x=0.0, y=0.0).distance_to(StagePoint(x=0.3, y=0.4)) == pytest.approx(0.5)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), 2.5])
    def test_a_coordinate_that_cannot_be_laid_out_is_refused(self, bad: float) -> None:
        # NaN would propagate silently through every later pass and only surface
        # as a blank frame; well past the safe area is a layout bug, not a style.
        with pytest.raises(ValidationError):
            StagePoint(x=bad, y=0.0)


class TestStageSize:
    """Extent, where zero is not a size."""

    def test_a_size_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            StageSize(width=0.0, height=1.0)


class TestStageBoundsConstruction:
    """Boxes are compiler output, so the guards catch compiler bugs."""

    def test_a_box_around_a_center_recovers_that_center_and_size(self) -> None:
        box = StageBounds.around(StagePoint(x=0.5, y=-0.25), StageSize(width=1.0, height=0.5))

        assert box.center.as_tuple() == pytest.approx((0.5, -0.25))
        assert (box.width, box.height, box.area) == pytest.approx((1.0, 0.5, 0.5))

    def test_inverted_bounds_are_refused(self) -> None:
        with pytest.raises(ValidationError):
            StageBounds(min_x=1.0, min_y=0.0, max_x=0.0, max_y=1.0)

    def test_non_finite_bounds_are_refused(self) -> None:
        with pytest.raises(ValidationError):
            StageBounds(min_x=0.0, min_y=0.0, max_x=float("nan"), max_y=1.0)

    def test_a_degenerate_box_is_legal(self) -> None:
        # A dot, or an object whose size the layout has not yet resolved. Rejecting
        # it would make the zero case a crash rather than something to lay out.
        point_box = StageBounds(min_x=0.5, min_y=0.5, max_x=0.5, max_y=0.5)

        assert (point_box.width, point_box.height, point_box.area) == (0.0, 0.0, 0.0)


class TestIntersection:
    """Read by IR304, where a shared edge must not count as occlusion."""

    @pytest.mark.parametrize(
        ("other", "expected"),
        [
            (StageBounds(min_x=1.0, min_y=0.0, max_x=2.0, max_y=1.0), False),
            (StageBounds(min_x=1.0, min_y=1.0, max_x=2.0, max_y=2.0), False),
            (StageBounds(min_x=2.0, min_y=0.0, max_x=3.0, max_y=1.0), False),
            (StageBounds(min_x=0.5, min_y=0.5, max_x=1.5, max_y=1.5), True),
            (StageBounds(min_x=0.25, min_y=0.25, max_x=0.75, max_y=0.75), True),
            (_UNIT, True),
        ],
    )
    def test_intersects_excludes_shared_edges_and_is_symmetric(
        self, other: StageBounds, expected: bool
    ) -> None:
        assert _UNIT.intersects(other) is expected
        assert other.intersects(_UNIT) is expected

    def test_a_partial_overlap_measures_the_shared_rectangle(self) -> None:
        other = StageBounds(min_x=0.5, min_y=0.5, max_x=1.5, max_y=1.5)

        assert _UNIT.intersection_area(other) == pytest.approx(0.25)
        assert other.intersection_area(_UNIT) == pytest.approx(0.25)

    def test_a_contained_box_contributes_its_whole_area(self) -> None:
        # IR304 divides by the *smaller* area, so this is the fully occluded case:
        # the small object is invisible and the finding must be unambiguous.
        inner = StageBounds(min_x=0.25, min_y=0.25, max_x=0.75, max_y=0.75)

        assert _UNIT.intersection_area(inner) == pytest.approx(inner.area)

    def test_touching_boxes_share_no_area(self) -> None:
        edge_to_edge = StageBounds(min_x=1.0, min_y=0.0, max_x=2.0, max_y=1.0)

        assert _UNIT.intersection_area(edge_to_edge) == 0.0


class TestContainment:
    """Read by IR305, where the safe area's own edges are inside it."""

    def test_a_box_contains_itself(self) -> None:
        assert _UNIT.contains(_UNIT)

    def test_the_safe_area_is_the_unit_square_and_holds_itself(self) -> None:
        # Content is authored against exactly this box in every aspect, so filling
        # it must be legal; pass P6 maps it to world units per format.
        assert (SAFE_AREA.min_x, SAFE_AREA.min_y, SAFE_AREA.max_x, SAFE_AREA.max_y) == (
            -1.0,
            -1.0,
            1.0,
            1.0,
        )
        assert SAFE_AREA.contains(SAFE_AREA)

    @pytest.mark.parametrize(
        "escaping",
        [
            StageBounds(min_x=-1.1, min_y=0.0, max_x=0.0, max_y=1.0),
            StageBounds(min_x=0.0, min_y=-1.1, max_x=1.0, max_y=0.0),
            StageBounds(min_x=0.0, min_y=0.0, max_x=1.1, max_y=1.0),
            StageBounds(min_x=0.0, min_y=0.0, max_x=1.0, max_y=1.1),
        ],
    )
    def test_a_box_poking_out_on_any_side_is_not_contained(self, escaping: StageBounds) -> None:
        assert not SAFE_AREA.contains(escaping)

    def test_containment_is_not_symmetric(self) -> None:
        inner = StageBounds(min_x=0.25, min_y=0.25, max_x=0.75, max_y=0.75)

        assert _UNIT.contains(inner)
        assert not inner.contains(_UNIT)


class TestUnionAndPadding:
    """How pass P5 turns "frame these objects" into a box to point a camera at."""

    def test_a_union_encloses_both_and_is_commutative(self) -> None:
        left = StageBounds(min_x=-1.0, min_y=-0.5, max_x=-0.5, max_y=0.5)
        right = StageBounds(min_x=0.5, min_y=-0.25, max_x=1.0, max_y=0.75)
        combined = left.union(right)

        assert combined.contains(left) and combined.contains(right)
        assert combined == right.union(left)
        assert (combined.min_x, combined.min_y, combined.max_x, combined.max_y) == (
            -1.0,
            -0.5,
            1.0,
            0.75,
        )

    def test_a_union_with_a_contained_box_changes_nothing(self) -> None:
        inner = StageBounds(min_x=0.25, min_y=0.25, max_x=0.75, max_y=0.75)

        assert _UNIT.union(inner) == _UNIT

    def test_padding_grows_every_side_about_the_same_center(self) -> None:
        padded = _UNIT.padded(0.1)

        assert (padded.width, padded.height) == pytest.approx((1.2, 1.2))
        assert padded.center.as_tuple() == pytest.approx(_UNIT.center.as_tuple())

    def test_negative_padding_tightens_the_frame(self) -> None:
        assert _UNIT.padded(-0.25).width == pytest.approx(0.5)

    def test_padding_a_box_out_of_existence_is_refused(self) -> None:
        # ``zoom_to`` with a negative padding on a small target. An inverted frame
        # is uninterpretable, so P5 should fail loudly rather than emit one.
        with pytest.raises(ValidationError):
            _UNIT.padded(-0.75)

    def test_union_all_encloses_every_box(self) -> None:
        boxes = [
            StageBounds(min_x=-0.8, min_y=-0.2, max_x=-0.4, max_y=0.2),
            StageBounds(min_x=-0.1, min_y=0.5, max_x=0.1, max_y=0.9),
            StageBounds(min_x=0.4, min_y=-0.6, max_x=0.8, max_y=-0.2),
        ]
        combined = union_all(boxes)

        assert combined is not None
        assert all(combined.contains(box) for box in boxes)
        assert (combined.min_x, combined.min_y, combined.max_x, combined.max_y) == pytest.approx(
            (-0.8, -0.6, 0.8, 0.9)
        )

    def test_union_all_of_one_box_is_that_box(self) -> None:
        assert union_all([_UNIT]) == _UNIT

    def test_union_all_of_nothing_is_none(self) -> None:
        # An empty scene has no extent, and None says so. Zero would frame the
        # camera on a point at the origin, which is a different claim entirely.
        assert union_all([]) is None
