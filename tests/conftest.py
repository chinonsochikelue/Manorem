"""Shared pytest configuration."""

from __future__ import annotations

import pytest

from manorem_core import configure_logging


@pytest.fixture(scope="session", autouse=True)
def _logging() -> None:
    configure_logging(level="WARNING", json_output=False)
