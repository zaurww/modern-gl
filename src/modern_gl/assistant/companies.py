"""The companies the assistant may read: the files of the program's folder, each opened as a
snapshot (D80) — the assistant cannot write, and the user's open file is not locked. The
snapshot is taken again when the file (or its WAL) changed, so answers follow the work."""

from __future__ import annotations

from pathlib import Path

from modern_gl.domain.errors import NotFoundError
from modern_gl.i18n import fold, tr
from modern_gl.infrastructure.db import Connection
from modern_gl.infrastructure.workspace import CompanyFile, Workspace

Stamp = tuple[tuple[int, int], ...]


class Companies:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self._open: dict[Path, tuple[Stamp, Connection, int]] = {}

    def files(self) -> list[CompanyFile]:
        return self.workspace.companies()

    def open(self, name: str = "") -> tuple[Connection, int]:
        """The company by its name (case and İ/ı, ə… do not matter; a unique beginning will
        do); with no name — the only company there is."""
        path = self._find(name).path
        stamp = _stamp(path)
        known = self._open.get(path)
        if known and known[0] == stamp:
            return known[1], known[2]
        if known:
            known[1].close()
        conn, company_id = self.workspace.view(path)
        self._open[path] = (stamp, conn, company_id)
        return conn, company_id

    def close(self) -> None:
        for _, conn, _ in self._open.values():
            conn.close()
        self._open.clear()

    def _find(self, name: str) -> CompanyFile:
        files = self.files()
        if not name.strip():
            if len(files) == 1:
                return files[0]
            raise NotFoundError(tr("укажите компанию: {names}", names=_names(files)))
        wanted = fold(name.strip())
        exact = [f for f in files if fold(f.name) == wanted]
        found = exact or [f for f in files if fold(f.name).startswith(wanted)]
        if len(found) == 1:
            return found[0]
        if not found:
            raise NotFoundError(
                tr("компания «{name}» не найдена; есть: {names}", name=name, names=_names(files))
            )
        raise NotFoundError(
            tr("«{name}» — несколько компаний: {names}", name=name, names=_names(found))
        )


def _names(files: list[CompanyFile]) -> str:
    return ", ".join(f.name for f in files) or "—"


def _stamp(path: Path) -> Stamp:
    """When the file and its WAL last changed: a new snapshot is needed when this does."""
    parts = []
    for p in (path, path.with_name(path.name + "-wal")):
        try:
            st = p.stat()
            parts.append((st.st_mtime_ns, st.st_size))
        except OSError:
            parts.append((0, 0))
    return tuple(parts)
