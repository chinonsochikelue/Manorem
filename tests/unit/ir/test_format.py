"""Format and style: the two places aspect and appearance are decided.

``FormatSpec`` is the whole of the aspect contract. One authored IR must compile
to 16:9, 9:16 and 1:1, and the only thing that varies between those three runs is
this object -- which is why no other module may hold a width, a height or an fps.
A hard-coded 1920 anywhere else silently defeats vertical output.

The other half is arithmetic the timeline depends on. ``seconds_to_frames`` is the
quantizer pass P4 snaps every resolved time through, so a committed RenderPlan
golden is only stable if this function is. The end-to-end check "video duration
equals summed ``duration_frames / fps`` within one frame" ultimately rests here.

``StyleTokens`` exists so a scene never names a hex value. Colors and sizes are
*roles* resolved during normalization, which is what makes restyling a project one
edit instead of hundreds -- and what lets an unknown role degrade to something
visible rather than to nothing.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from manorem_ir import (
    FPS_BY_QUALITY,
    RESOLUTIONS,
    Aspect,
    FormatSpec,
    StyleTokens,
)

_QUALITIES = ("draft", "medium", "final")


class TestAspectRatios:
    """The three targets, and the numbers their names promise."""

    @pytest.mark.parametrize(
        ("aspect", "ratio"),
        [
            (Aspect.WIDESCREEN, 16 / 9),
            (Aspect.VERTICAL, 9 / 16),
            (Aspect.SQUARE, 1.0),
        ],
    )
    def test_the_ratio_is_read_from_the_name(self, aspect: Aspect, ratio: float) -> None:
        assert aspect.ratio == pytest.approx(ratio)

    def test_vertical_is_the_reciprocal_of_widescreen(self) -> None:
        # Stated as an assertion because a typo'd enum value would otherwise only
        # surface as a letterboxed render nobody looks at until delivery.
        assert Aspect.VERTICAL.ratio == pytest.approx(1.0 / Aspect.WIDESCREEN.ratio)


class TestResolutionTable:
    """Every (aspect, quality) pair the CLI can be asked for."""

    def test_every_aspect_has_every_quality_tier(self) -> None:
        assert set(RESOLUTIONS) == {(aspect, q) for aspect in Aspect for q in _QUALITIES}

    def test_every_listed_resolution_matches_its_aspect(self) -> None:
        # A single transposed pair here would produce a stretched render that still
        # exits zero, so the whole table is swept and every offender named.
        bad = [
            f"{aspect.value}/{quality}={width}x{height}"
            for (aspect, quality), (width, height) in RESOLUTIONS.items()
            if abs(width / height - aspect.ratio) / aspect.ratio > 0.02
        ]

        assert bad == []

    def test_fps_rises_with_quality(self) -> None:
        assert [FPS_BY_QUALITY[q] for q in _QUALITIES] == [15, 30, 60]

    def test_every_quality_tier_has_an_fps(self) -> None:
        assert set(FPS_BY_QUALITY) == set(_QUALITIES)

    def test_draft_is_the_cheapest_tier(self) -> None:
        # Goldens render at draft, so it has to stay the smallest of the three.
        areas = {q: RESOLUTIONS[(Aspect.WIDESCREEN, q)] for q in _QUALITIES}

        assert areas["draft"][0] * areas["draft"][1] == min(w * h for w, h in areas.values())


class TestForQuality:
    """The constructor the CLI actually calls."""

    @pytest.mark.parametrize("aspect", list(Aspect))
    @pytest.mark.parametrize("quality", _QUALITIES)
    def test_it_agrees_with_the_tables(self, aspect: Aspect, quality: str) -> None:
        spec = FormatSpec.for_quality(aspect, quality)

        assert (spec.width, spec.height) == RESOLUTIONS[(aspect, quality)]
        assert spec.fps == FPS_BY_QUALITY[quality]
        assert spec.aspect is aspect

    def test_the_default_is_a_widescreen_draft(self) -> None:
        assert FormatSpec.for_quality() == FormatSpec()

    def test_an_unknown_tier_names_itself(self) -> None:
        # Read by whoever passed ``--quality hi``, so it has to echo the value.
        with pytest.raises(ValueError, match="'hi'"):
            FormatSpec.for_quality(Aspect.WIDESCREEN, "hi")


class TestDimensionsAgreeWithAspect:
    """The guard that keeps a stretched render from exiting zero."""

    def test_a_transposed_pair_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            FormatSpec(aspect=Aspect.VERTICAL, width=1920, height=1080)

    def test_a_square_claim_over_a_wide_frame_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            FormatSpec(aspect=Aspect.SQUARE, width=1280, height=720)

    def test_rounding_to_even_pixels_is_tolerated(self) -> None:
        # 854x480 is 1.779 against 16:9's 1.778 -- the standard 480p width, and the
        # reason the check has a tolerance rather than demanding exactness.
        spec = FormatSpec(aspect=Aspect.WIDESCREEN, width=854, height=480)

        assert spec.width / spec.height != pytest.approx(Aspect.WIDESCREEN.ratio, abs=1e-6)

    def test_the_message_names_both_ratios(self) -> None:
        # The author has to see what they asked for next to what it implies.
        with pytest.raises(ValidationError, match="do not match aspect"):
            FormatSpec(aspect=Aspect.SQUARE, width=1920, height=1080)


class TestFrameQuantization:
    """The quantizer every resolved time passes through in pass P4."""

    def test_the_frame_duration_is_the_reciprocal_of_fps(self) -> None:
        assert FormatSpec.for_quality(quality="draft").frame_duration == pytest.approx(1 / 15)
        assert FormatSpec.for_quality(quality="final").frame_duration == pytest.approx(1 / 60)

    @pytest.mark.parametrize(
        ("seconds", "frames"),
        [(0.0, 0), (1.0, 15), (2.0, 30), (3.533, 53), (0.5, 8), (0.0667, 1)],
    )
    def test_seconds_become_whole_frames(self, seconds: float, frames: int) -> None:
        # 3.533s at 15fps is 53 frames: the figure the scheduling probe measured
        # out of Manim, and the reason the compiler is allowed to own all timing.
        assert FormatSpec.for_quality(quality="draft").seconds_to_frames(seconds) == frames

    def test_a_half_frame_rounds_up(self) -> None:
        # Deterministic in the direction that never truncates a visible frame.
        spec = FormatSpec.for_quality(quality="draft")

        assert spec.seconds_to_frames(1.0 / 30.0) == 1

    def test_less_than_half_a_frame_quantizes_away(self) -> None:
        # Recorded rather than fixed here: at 15fps a 20ms beat *is* zero frames.
        # Padding it back to one frame is autofix's job under the mechanically-safe
        # rule, and P8's positive-duration invariant is what catches it if not.
        assert FormatSpec.for_quality(quality="draft").seconds_to_frames(0.02) == 0

    def test_frames_convert_back_to_seconds(self) -> None:
        spec = FormatSpec.for_quality(quality="medium")

        assert spec.frames_to_seconds(45) == pytest.approx(1.5)

    @pytest.mark.parametrize("seconds", [0.0, 0.7, 1.0, 3.533, 12.25])
    def test_the_round_trip_lands_within_half_a_frame(self, seconds: float) -> None:
        # The property the end-to-end duration check depends on: quantization may
        # move a time, but never by enough to read as a desync.
        spec = FormatSpec.for_quality(quality="draft")
        recovered = spec.frames_to_seconds(spec.seconds_to_frames(seconds))

        assert abs(recovered - seconds) <= spec.frame_duration / 2

    def test_quantization_is_monotonic(self) -> None:
        # Cue order survives quantization: a cue authored later must never be
        # scheduled earlier once snapped to frames.
        spec = FormatSpec.for_quality(quality="draft")
        counts = [spec.seconds_to_frames(t / 100.0) for t in range(400)]

        assert counts == sorted(counts)

    def test_higher_fps_gives_finer_resolution(self) -> None:
        assert FormatSpec.for_quality(quality="final").seconds_to_frames(1.0) == 60


class TestFormatIsFrozenAndRetargetable:
    """A format is data, and swapping it is the whole aspect story."""

    def test_a_spec_cannot_be_mutated(self) -> None:
        with pytest.raises(ValidationError):
            FormatSpec().width = 1920

    def test_specs_compare_by_value(self) -> None:
        # Render caching keys on the format, so two equal specs must be one key.
        assert FormatSpec.for_quality(Aspect.SQUARE) == FormatSpec.for_quality(Aspect.SQUARE)
        assert FormatSpec.for_quality(Aspect.SQUARE) != FormatSpec.for_quality(Aspect.VERTICAL)

    def test_an_absurd_bitrate_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            FormatSpec(bitrate_kbps=1)

    def test_no_bitrate_means_the_encoder_decides(self) -> None:
        assert FormatSpec().bitrate_kbps is None


class TestStyleTokens:
    """Roles in, concrete values out -- and never a crash on an unknown role."""

    def test_every_color_role_resolves_to_its_token(self) -> None:
        style = StyleTokens()
        roles = ("primary", "secondary", "accent", "muted", "text", "success", "background")

        assert {role: style.color_for(role) for role in roles} == {
            "primary": style.primary,
            "secondary": style.secondary,
            "accent": style.accent,
            "muted": style.muted,
            "text": style.text,
            "success": style.success,
            "background": style.background,
        }

    def test_an_unknown_color_role_falls_back_to_primary(self) -> None:
        # A misspelled role should render in the wrong colour, not vanish: an
        # invisible object is far harder to diagnose than a mis-tinted one.
        assert StyleTokens().color_for("chartreuse") == StyleTokens().primary

    def test_the_type_scale_descends(self) -> None:
        style = StyleTokens()
        sizes = [style.size_for(r) for r in ("title", "heading", "body", "caption")]

        assert sizes == sorted(sizes, reverse=True)

    def test_an_unknown_size_role_falls_back_to_body(self) -> None:
        assert StyleTokens().size_for("subtitle") == StyleTokens().body_size

    def test_sizes_are_in_stage_units(self) -> None:
        # Not points and not pixels: pass P6 maps these to world units per format,
        # which is what keeps text legible at 480p and at 1080p alike.
        assert StyleTokens().title_size <= 1.0

    @pytest.mark.parametrize("bad", ["5AB2FF", "#5AB2F", "#GGGGGG", "blue", "#5ab2ff88"])
    def test_a_colour_that_is_not_a_six_digit_hex_is_refused(self, bad: str) -> None:
        # The renderer passes these straight to Manim; a bare colour name would
        # fail there, far from the style file that introduced it.
        with pytest.raises(ValidationError):
            StyleTokens(primary=bad)

    def test_lowercase_hex_is_accepted(self) -> None:
        assert StyleTokens(primary="#5ab2ff").primary == "#5ab2ff"

    def test_a_non_positive_default_duration_is_refused(self) -> None:
        # It seeds every cue that omits a length, so zero would produce a scene of
        # zero-length animations rather than one obvious failure.
        with pytest.raises(ValidationError):
            StyleTokens(default_op_duration=0.0)

    def test_tokens_are_frozen(self) -> None:
        with pytest.raises(ValidationError):
            StyleTokens().primary = "#000000"
