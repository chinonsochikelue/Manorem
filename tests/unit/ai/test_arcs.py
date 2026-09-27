"""Named story arcs: the menu the story agent chooses from."""

from __future__ import annotations

from manorem_ai import StoryArc, arc_menu, get_arc


def test_known_arc_resolves() -> None:
    arc = get_arc("question_led")
    assert isinstance(arc, StoryArc)
    assert arc.name == "question_led"
    assert arc.roles  # a non-empty ordered role sequence


def test_unknown_arc_is_none() -> None:
    assert get_arc("no_such_arc") is None


def test_arc_menu_lists_every_arc() -> None:
    menu = arc_menu()
    for name in ("question_led", "problem_solution", "chronological", "comparison"):
        assert name in menu
