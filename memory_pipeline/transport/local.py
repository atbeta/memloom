"""Local filesystem transport. Trivial — just delegates to pathlib."""
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from .base import FileStat, normalize_path


class LocalTransport:
    name = "local"

    def __init__(self, root: str | os.PathLike | None = None) -> None:
        self.root = Path(root).expanduser() if root else Path(".").resolve()

    def _abs(self, path: str) -> Path:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self.root / p
        return p

    def exists(self, path: str) -> bool:
        return self._abs(path).exists()

    def stat(self, path: str) -> FileStat:
        return FileStat.from_local(self._abs(path))

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        return self._abs(path).read_text(encoding=encoding, errors="replace")

    def read_bytes(self, path: str) -> bytes:
        return self._abs(path).read_bytes()

    def glob(self, pattern: str) -> list[str]:
        """Glob. Splits a pattern like 'memory/*.md' into (dir, pattern) for pathlib.

        - Bare filename ('MEMORY.md') → resolve under root and check existence
        - Relative pattern ('memory/*.md') → glob under root
        - Absolute pattern ('/abs/path/*.x') → use directly
        - Recursive ('**/*.jsonl') → pathlib handles natively
        """
        p = Path(pattern).expanduser()
        if p.is_absolute():
            base = p.parent
            pat = p.name or "*"
            return sorted(normalize_path(str(x)) for x in base.glob(pat) if x.exists())
        # relative — resolve under root
        full_pattern = self.root / p
        base = full_pattern.parent
        pat = full_pattern.name or "*"
        if not base.exists():
            return []
        return sorted(normalize_path(str(x)) for x in base.glob(pat) if x.exists())

    def walk(self, root: str) -> Iterator[tuple[str, list[str], list[str]]]:
        """Yield (relative_dir, dirs, files) under `root`."""
        abs_root = self._abs(root)
        if not abs_root.exists():
            return iter(())
        base = abs_root
        for dirpath, dirnames, filenames in os.walk(abs_root):
            dirpath_p = Path(dirpath)
            rel = normalize_path(str(dirpath_p.relative_to(base))) if dirpath_p != base else ""
            yield rel, sorted(dirnames), sorted(filenames)


__all__ = ["LocalTransport"]
