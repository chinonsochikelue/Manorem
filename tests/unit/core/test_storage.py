"""Path containment is a security boundary, so escapes must raise, not clamp."""

from __future__ import annotations

from pathlib import Path

import pytest

from manorem_core import LocalFSStore, ObjectStore, UnsafePathError, validate_key


class TestValidateKey:
    @pytest.mark.parametrize(
        "key",
        ["a.json", "scenes/01/plan.json", "a/b/c/d.mp4", "with-dash_and_underscore.txt"],
    )
    def test_accepts_relative_posix_keys(self, key: str) -> None:
        assert validate_key(key) == key

    @pytest.mark.parametrize(
        ("key", "reason"),
        [
            ("../secrets.env", "parent traversal"),
            ("a/../../b", "nested traversal"),
            ("./a.json", "current-dir segment"),
            ("a//b.json", "empty segment"),
            ("/etc/passwd", "absolute posix"),
            ("C:/Windows/system32", "drive letter"),
            ("a\\b", "backslash separator"),
            ("", "empty"),
            (" a.json", "untrimmed"),
            ("x" * 1100, "over length"),
        ],
    )
    def test_rejects_unsafe_keys(self, key: str, reason: str) -> None:
        with pytest.raises(UnsafePathError):
            validate_key(key)


class TestLocalFSStore:
    def test_satisfies_object_store_protocol(self, tmp_path: Path) -> None:
        assert isinstance(LocalFSStore(tmp_path), ObjectStore)

    def test_round_trips_text_and_bytes(self, tmp_path: Path) -> None:
        store = LocalFSStore(tmp_path)
        store.put_text("a/b.json", '{"k":1}')
        store.put_bytes("a/c.bin", b"\x00\x01")

        assert store.get_text("a/b.json") == '{"k":1}'
        assert store.get_bytes("a/c.bin") == b"\x00\x01"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        store = LocalFSStore(tmp_path)
        store.put_text("deeply/nested/path/f.txt", "x")

        assert (tmp_path / "deeply" / "nested" / "path" / "f.txt").exists()

    def test_exists_reports_presence(self, tmp_path: Path) -> None:
        store = LocalFSStore(tmp_path)
        assert not store.exists("nope.json")
        store.put_text("nope.json", "{}")
        assert store.exists("nope.json")

    def test_put_file_copies_source(self, tmp_path: Path) -> None:
        source = tmp_path / "source.mp4"
        source.write_bytes(b"video")
        store = LocalFSStore(tmp_path / "store")
        store.put_file("renders/out.mp4", source)

        assert store.get_bytes("renders/out.mp4") == b"video"

    def test_local_path_stays_inside_root(self, tmp_path: Path) -> None:
        store = LocalFSStore(tmp_path)
        assert store.local_path("scenes/a.mp4").is_relative_to(store.root)

    def test_escape_attempts_raise_on_every_method(self, tmp_path: Path) -> None:
        store = LocalFSStore(tmp_path)
        for call in (
            lambda: store.put_text("../escaped.txt", "x"),
            lambda: store.get_bytes("../../etc/passwd"),
            lambda: store.local_path("../../x.mp4"),
            lambda: store.exists("../x"),
        ):
            with pytest.raises(UnsafePathError):
                call()

    def test_list_keys_returns_sorted_relative_posix(self, tmp_path: Path) -> None:
        store = LocalFSStore(tmp_path)
        store.put_text("b.json", "{}")
        store.put_text("a/c.json", "{}")

        assert store.list_keys() == ["a/c.json", "b.json"]

    def test_list_keys_filters_by_prefix(self, tmp_path: Path) -> None:
        store = LocalFSStore(tmp_path)
        store.put_text("scenes/a.json", "{}")
        store.put_text("renders/b.mp4", "x")

        assert store.list_keys("scenes") == ["scenes/a.json"]

    def test_list_keys_of_missing_prefix_is_empty(self, tmp_path: Path) -> None:
        assert LocalFSStore(tmp_path).list_keys("absent") == []
