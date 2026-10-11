"""Gemini credential resolution: one resolver, so no call site picks a key.

Every Manorem component that reaches Gemini asks this module, and only this
module, which credential it may use::

    Tool  ->  GeminiCredentialResolver  ->  environment variable  ->  GeminiProvider

Nothing else reads a Gemini key from the environment. That is what keeps the
answer to "which credential did the scene stage use?" in one reviewable place
instead of scattered across ``os.environ`` reads, and what lets a run be
switched between one shared credential and per-tool credentials by changing
configuration rather than code.

Two modes, selected by ``MANOREM_GEMINI_KEY_MODE``:

``shared``
    Every tool resolves to ``MANOREM_GEMINI_APIKEY`` (the legacy
    ``MANOREM_GEMINI_API_KEY`` spelling is still honoured). This is the
    behaviour Manorem shipped with before per-tool credentials existed.

``dedicated``
    Each tool resolves to its own ``MANOREM_<TOOL>_GEMINI_APIKEY``. A missing
    variable is a :class:`~manorem_core.errors.ConfigError` naming that
    variable -- never a silent substitution of another tool's credential. The
    substitution that *can* be enabled is spelled out and off by default:
    ``MANOREM_GEMINI_ALLOW_SHARED_FALLBACK=true`` lets a tool without a
    dedicated key fall back to the shared one.

Credentials are isolated, not multiplied: keys issued by the same Gemini project
share that project's quota, so dedicated mode is for keeping workloads legible
and separately rotatable, not for outrunning a provider limit.
"""

from __future__ import annotations

from pydantic import SecretStr

from manorem_core.errors import ConfigError
from manorem_core.settings import (
    PIPELINE_GEMINI_TOOLS,
    GeminiKeyMode,
    GeminiTool,
    Settings,
    get_settings,
)

__all__ = [
    "PIPELINE_GEMINI_TOOLS",
    "GeminiCredentialResolver",
    "GeminiKeyMode",
    "GeminiTool",
    "gemini_credentials",
]

#: Where dedicated mode looks for each tool's credential: ``tool -> Settings``
#: attribute. It is the tool's own name plus ``_gemini_apikey``, which is exactly
#: what pydantic-settings makes of ``MANOREM_<TOOL>_GEMINI_APIKEY`` under the
#: ``MANOREM_`` prefix -- so the variable a user sets and the field read here
#: cannot drift apart unnoticed (``test_gemini_credentials`` checks every tool).
_TOOL_FIELDS: dict[GeminiTool, str] = {tool: f"{tool.value}_gemini_apikey" for tool in GeminiTool}


class GeminiCredentialResolver:
    """Resolve one tool's Gemini credential from settings, and validate up front.

    The resolver holds no key of its own and performs no I/O: it reads
    :class:`~manorem_core.settings.Settings`, decides which variable applies, and
    returns the value only to the caller that is about to build a client. Its
    error messages name variables and modes, never values.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def mode(self) -> GeminiKeyMode:
        return self._settings.gemini_key_mode

    @staticmethod
    def variable_for(tool: GeminiTool) -> str:
        """The variable ``tool`` reads in dedicated mode (see also ``tool.env_var``)."""
        return tool.env_var

    def key(self, tool: GeminiTool) -> str:
        """The credential ``tool`` must use, or raise naming what is missing.

        Shared mode short-circuits to the single credential. Dedicated mode
        reads the tool's own variable and, only when
        ``MANOREM_GEMINI_ALLOW_SHARED_FALLBACK`` is on, may fall back to the
        shared one -- a documented substitution, never a silent one.
        """
        if self.mode is GeminiKeyMode.SHARED:
            return self._settings.gemini_key_or_raise

        dedicated = getattr(self._settings, _TOOL_FIELDS[tool])
        if isinstance(dedicated, SecretStr):
            return dedicated.get_secret_value()
        if self._settings.gemini_allow_shared_fallback:
            return self._settings.gemini_key_or_raise
        raise ConfigError(
            f"Missing Gemini credential:\n{tool.env_var}\n"
            "Set it, or set MANOREM_GEMINI_KEY_MODE=shared to serve every tool "
            "from MANOREM_GEMINI_APIKEY. MANOREM_GEMINI_ALLOW_SHARED_FALLBACK=true "
            f"lets {tool.value!r} borrow the shared credential instead."
        )

    def validate(self, *tools: GeminiTool) -> None:
        """Fail at startup, before any request, if a needed credential is absent.

        Called with the tools a given backend will actually use: a live Gemini
        run needs every pipeline stage's credential (or the shared one), while a
        recording run needs only ``CASSETTE``'s. Called with nothing, it checks
        every tool in the enum. Offline and replay runs call this never -- they
        construct no client, so requiring a key there would break ``--offline``.
        """
        if self.mode is GeminiKeyMode.SHARED:
            _ = self._settings.gemini_key_or_raise  # the one credential, checked for
            return
        for tool in tools or tuple(GeminiTool):
            self.key(tool)


def gemini_credentials(settings: Settings | None = None) -> GeminiCredentialResolver:
    """A resolver over ``settings`` (the process settings when omitted)."""
    return GeminiCredentialResolver(settings or get_settings())
