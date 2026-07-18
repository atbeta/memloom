"""Transport abstraction: how collectors read files from a host.

A Transport answers 3 questions:
  1. Can I read this path?  (exists, is_file, is_dir, stat)
  2. Give me content of one file.  (read_text, read_bytes)
  3. List files in a directory matching a glob.  (glob)

That's the entire API. Anything more complex (incremental SQLite, S3, Notion)
lives in its own collector.
"""
from __future__ import annotations

import stat as _stat
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol, runtime_checkable


@dataclass
class FileStat:
    """Minimal file metadata, transport-agnostic."""
    path: str
    size: int
    mtime_ms: int           # ms epoch
    mode: int               # permission bits
    is_dir: bool
    is_file: bool

    @classmethod
    def from_local(cls, p: Path) -> FileStat:
        st = p.stat()
        return cls(
            path=str(p),
            size=st.st_size,
            mtime_ms=int(st.st_mtime * 1000),
            mode=st.st_mode,
            is_dir=_stat.S_ISDIR(st.st_mode),
            is_file=_stat.S_ISDIR(st.st_mode) is False and _stat.S_ISREG(st.st_mode),
        )


@runtime_checkable
class Transport(Protocol):
    """Read-only file access. Identical surface for local and SSH."""
    name: str

    def exists(self, path: str) -> bool: ...
    def stat(self, path: str) -> FileStat: ...
    def read_text(self, path: str, encoding: str = "utf-8") -> str: ...
    def read_bytes(self, path: str) -> bytes: ...
    def glob(self, pattern: str) -> list[str]: ...
    def walk(self, root: str) -> Iterator[tuple[str, list[str], list[str]]]:
        """Like os.walk but yields POSIX-style relative paths under `root`."""
        ...


def normalize_path(path: str) -> str:
    """Normalize to forward-slash POSIX style (works across local + SSH)."""
    return str(PurePosixPath(path.replace("\\", "/")))


__all__ = ["Transport", "FileStat", "normalize_path"]
