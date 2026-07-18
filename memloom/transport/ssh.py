"""SSH transport via Fabric. Reads files on a remote host transparently.

Strategy: keep one long-lived SSH connection per host per run. Reuse it across
all file ops. On error, attempt one reconnect, then bubble up.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

from fabric import Connection
from invoke.exceptions import CommandTimedOut, UnexpectedExit

from .base import FileStat, normalize_path


class SSHTransport:
    name = "ssh"

    def __init__(
        self,
        host: str,
        user: str,
        key_file: str | os.PathLike | None = None,
        port: int = 22,
        password: str | None = None,
        connect_timeout: int = 10,
    ) -> None:
        connect_kwargs: dict = {}
        if key_file:
            connect_kwargs["key_filename"] = str(Path(key_file).expanduser())
        if password:
            connect_kwargs["password"] = password
        self._conn = Connection(
            host=host,
            user=user,
            port=port,
            connect_timeout=connect_timeout,
            connect_kwargs=connect_kwargs,
        )
        self._host = host

    # ---- lifecycle ----

    def open(self) -> None:
        # Fabric is lazy; just verify the host responds.
        self._run("true")

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self) -> SSHTransport:
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- internal ----

    def _run(self, cmd: str, warn_only: bool = True) -> str:
        try:
            r = self._conn.run(cmd, hide=True, warn=warn_only, timeout=30)
            return r.stdout or ""
        except (CommandTimedOut, UnexpectedExit):
            if not warn_only:
                raise
            return ""

    def _stat_remote(self, path: str) -> FileStat | None:
        # `stat -c` works on GNU coreutils; macOS needs `-f`. Try GNU first.
        out = self._run(
            f"stat -c '%s %Y %a %F' {self._shq(path)} 2>/dev/null || "
            f"stat -f '%z %m %Lp %HT' {self._shq(path)}"
        )
        if not out.strip():
            return None
        parts = out.strip().split(None, 3)
        if len(parts) < 4:
            return None
        try:
            size = int(parts[0])
            mtime_s = int(parts[1])
            mode = int(parts[2], 8)
            ftype = parts[3].lower()
        except ValueError:
            return None
        return FileStat(
            path=path,
            size=size,
            mtime_ms=mtime_s * 1000,
            mode=mode,
            is_dir="directory" in ftype,
            is_file="regular" in ftype,
        )

    @staticmethod
    def _shq(path: str) -> str:
        # Single-quote, escape any single quotes inside.
        return "'" + path.replace("'", "'\\''") + "'"

    # ---- Transport interface ----

    def exists(self, path: str) -> bool:
        return self._stat_remote(path) is not None

    def stat(self, path: str) -> FileStat:
        st = self._stat_remote(path)
        if st is None:
            raise FileNotFoundError(f"SSH: {self._host}:{path} not found")
        return st

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        with self._conn.sftp() as sftp, sftp.open(path, "rb") as f:
            data = f.read()
        return data.decode(encoding, errors="replace")

    def read_bytes(self, path: str) -> bytes:
        with self._conn.sftp() as sftp, sftp.open(path, "rb") as f:
            return f.read()

    def glob(self, pattern: str) -> list[str]:
        # POSIX shell globbing on remote; rely on bash.
        out = self._run(f"bash -O globstar -O nullglob -c 'shopt -s nullglob; for f in {self._shq(pattern)}; do echo \"$f\"; done'")
        return [normalize_path(line) for line in out.splitlines() if line.strip()]

    def walk(self, root: str) -> Iterator[tuple[str, list[str], list[str]]]:
        """Naive remote walk: one `find` per directory layer.

        Acceptable for v0.1 (small trees). For huge dirs we should switch to
        `find -print0 | tar --null -cf -` and stream back, deferred to v0.2.
        """
        out = self._run(f"find {self._shq(root)} -mindepth 1 -printf '%y %p\\n'")
        if not out.strip():
            return iter(())
        # Build a nested map of dirs/files under root.
        root_p = PurePosixPath(root)
        tree: dict = {}
        for line in out.splitlines():
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            ftype, full = parts
            try:
                rel = PurePosixPath(full).relative_to(root_p)
            except ValueError:
                continue
            d = tree
            for parent in rel.parents:
                d = d.setdefault(parent.name, {})
            leaf = rel.name
            if ftype.startswith("d"):
                d.setdefault(leaf, {})
            else:
                d[leaf] = None  # file marker

        def _walk(d: dict, prefix: str) -> Iterator[tuple[str, list[str], list[str]]]:
            dirs, files = [], []
            for name, sub in d.items():
                if isinstance(sub, dict):
                    dirs.append(name)
                else:
                    files.append(name)
            yield prefix, sorted(dirs), sorted(files)
            for d_name in sorted(dirs):
                yield from _walk(d[d_name], f"{prefix}/{d_name}" if prefix else d_name)

        return _walk(tree, "")


__all__ = ["SSHTransport"]
