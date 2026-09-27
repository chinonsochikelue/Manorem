"""Object storage abstraction.

The engine never touches raw paths directly: every read and write goes through a
store rooted at a workspace directory, and every key is checked for escape. This
is the same seam that later swaps ``LocalFSStore`` for an S3 implementation
without the renderer or compositor noticing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from manorem_core.errors import UnsafePathError


def validate_key(key: str) -> str:
    """Reject anything that could escape the store root.

    Absolute paths, drive letters, ``..`` segments and backslashes are refused
    outright rather than sanitized -- a caller producing such a key has a bug, and
    quietly rewriting it would hide it.
    """
    if not key or key != key.strip():
        raise UnsafePathError(f"storage key must be non-empty and untrimmed-free: {key!r}")
    if "\\" in key:
        raise UnsafePathError(f"storage key must use forward slashes: {key!r}")
    if key.startswith("/"):
        raise UnsafePathError(f"storage key must be relative: {key!r}")
    # Split the raw string: PurePosixPath silently normalizes away "." segments,
    # which would let "./x" through a parts-based check.
    segments = key.split("/")
    if any(seg in {"..", ".", ""} for seg in segments):
        raise UnsafePathError(f"storage key must not contain relative or empty segments: {key!r}")
    if len(key) > 1024 or ":" in key:
        raise UnsafePathError(f"storage key is not a portable relative path: {key!r}")
    return key


@runtime_checkable
class ObjectStore(Protocol):
    """Content store addressed by forward-slash relative keys."""

    def put_bytes(self, key: str, data: bytes) -> str: ...

    def put_text(self, key: str, text: str) -> str: ...

    def put_file(self, key: str, source: Path) -> str: ...

    def get_bytes(self, key: str) -> bytes: ...

    def get_text(self, key: str) -> str: ...

    def exists(self, key: str) -> bool: ...

    def local_path(self, key: str) -> Path: ...

    def list_keys(self, prefix: str = "") -> list[str]: ...


class LocalFSStore:
    """Filesystem-backed store confined to ``root``.

    ``local_path`` exists because Manim and FFmpeg are subprocesses that need real
    paths; it re-checks containment so a caller cannot obtain a path outside the
    root even by constructing keys dynamically.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, key: str) -> Path:
        candidate = (self._root / validate_key(key)).resolve()
        if not candidate.is_relative_to(self._root):
            raise UnsafePathError(f"resolved path escapes store root: {key!r}")
        return candidate

    def put_bytes(self, key: str, data: bytes) -> str:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return key

    def put_text(self, key: str, text: str) -> str:
        return self.put_bytes(key, text.encode("utf-8"))

    def put_file(self, key: str, source: Path) -> str:
        return self.put_bytes(key, source.read_bytes())

    def get_bytes(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def get_text(self, key: str) -> str:
        return self.get_bytes(key).decode("utf-8")

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def local_path(self, key: str) -> Path:
        """Real filesystem path for a key, with its parent created."""
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def list_keys(self, prefix: str = "") -> list[str]:
        base = self._resolve(prefix) if prefix else self._root
        if not base.exists():
            return []
        return sorted(p.relative_to(self._root).as_posix() for p in base.rglob("*") if p.is_file())
