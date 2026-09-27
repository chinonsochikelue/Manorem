"""The Visual QA seam: designed in, unimplemented in M1.

The one behavioural guarantee M1 makes is that nothing claims to have assessed a
render it never looked at. :class:`NoopVisualQA` returns ``None`` -- *not
assessed* -- and satisfies the :class:`VisualQA` protocol so the real stage drops
in behind the same seam later.
"""

from __future__ import annotations

from manorem_ai import NoopVisualQA, VisualQA


def test_noop_declines_to_assess() -> None:
    qa = NoopVisualQA()
    # ``plan``/``result`` are unused by the no-op; None is the "not assessed" signal.
    assert qa.assess(None, None) is None  # type: ignore[arg-type]


def test_noop_satisfies_the_protocol() -> None:
    assert isinstance(NoopVisualQA(), VisualQA)
