"""Shared pytest configuration."""

from __future__ import annotations

import os

import pytest

from manorem_core import configure_logging
from manorem_core.settings import Settings, get_settings


@pytest.fixture(scope="session", autouse=True)
def _logging() -> None:
    configure_logging(level="WARNING", json_output=False)


@pytest.fixture(autouse=True)
def _hermetic_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ``Settings`` out of the developer's real environment.

    The repo root carries a ``.env`` with live ``MANOREM_*`` credentials for
    recording cassettes, and ``Settings`` reads it by default. Tests that assert
    on configuration (credential resolution, audio defaults) must see the shipped
    defaults, not whatever a given machine has in ``.env`` or exported -- otherwise
    a populated ``.env`` turns deterministic tests into machine-dependent ones.
    So for every test: drop ``MANOREM_*`` from the environment and stop ``Settings``
    from loading the dotenv file. A test that wants a value sets it explicitly
    (``Settings(...)`` or ``monkeypatch.setenv``), which still works.
    """
    for name in list(os.environ):
        if name.startswith("MANOREM_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
