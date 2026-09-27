"""The ``manorem`` command line -- five verbs over the idea-to-video pipeline.

The Typer application and its console-script entry point live in
:mod:`manorem_cli.app`; they are re-exported here so ``from manorem_cli import
app`` works and the commands are discoverable from the package root.
"""

from __future__ import annotations

from manorem_cli.app import app, main

__all__ = ["app", "main"]
