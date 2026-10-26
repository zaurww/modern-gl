"""Files of earlier releases, updated by this program (D-new): each `schema_NNNN.gl.xz` in
tests/fixtures/upgrade was written by the program of that schema
(`scripts/upgrade_fixture.py`) with the year demo, every module; with it is what that
program reported. After the update the file is whole, reports the same numbers, and every
module builds from its documents exactly the postings it holds.

A failure here is a mistake of a migration — or of a change to a report: then say so in
the commit and write the fixture's json anew, never the migration."""

from __future__ import annotations

import importlib.util
import json
import lzma
from pathlib import Path

import pytest

from modern_gl.application.ledger import Ledger
from modern_gl.application.rebuild import module_rebuilders
from modern_gl.application.workspace import Workspace
from modern_gl.i18n import DEFAULT, language, set_language
from modern_gl.infrastructure.db import close, latest_version, schema_version

FIXTURES = Path(__file__).parent / "fixtures" / "upgrade"
SCRIPT = Path(__file__).parent.parent / "scripts" / "upgrade_fixture.py"


def _fixture_script():
    spec = importlib.util.spec_from_file_location("upgrade_fixture", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(
    scope="module", params=sorted(FIXTURES.glob("schema_*.gl.xz")), ids=lambda p: p.name[:11]
)
def updated(request, tmp_path_factory):
    """The file of an earlier release, opened (so updated) by this program."""
    folder = tmp_path_factory.mktemp("upgrade")
    ws = Workspace(folder)
    path = folder / "Firma.gl"
    path.write_bytes(lzma.decompress(request.param.read_bytes()))
    stored = json.loads(
        request.param.with_name(request.param.name[:11] + ".json").read_text("utf-8")
    )
    conn, company_id = ws.open(path)
    yield ws, path, conn, company_id, stored
    close(conn)


def test_there_is_a_file_of_the_current_schema():
    """Each release adds the file of its schema: the next update is tested on it."""
    assert (FIXTURES / f"schema_{latest_version():04d}.gl.xz").exists(), (
        "новая схема: uv run python scripts/upgrade_fixture.py tests/fixtures/upgrade"
    )


def test_the_file_is_updated_whole(updated):
    ws, path, conn, company_id, stored = updated
    assert schema_version(conn) == latest_version()
    assert company_id == stored["company_id"]
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    if stored["schema"] < latest_version():
        [made] = ws.backups(path)  # the file as the older program left it
        assert "до обновления" in made.path.name


def test_the_numbers_are_those_of_the_older_program(updated):
    _ws, _path, conn, company_id, stored = updated
    found = json.loads(json.dumps(_fixture_script().expected(conn, company_id)))
    for key, value in found.items():
        assert value == stored[key], key


def test_every_module_builds_the_postings_it_holds(updated):
    """The documents of the modules survived the update: built anew from the first day,
    they give exactly the postings in the file."""
    _ws, _path, conn, company_id, _stored = updated
    ledger = Ledger(conn)
    ledger.set_closed_through(company_id, None)
    was = language()
    set_language(DEFAULT)  # the texts of the postings are in the file's language
    try:
        for name, module in module_rebuilders(ledger).items():
            assert module.rebuild_postings(company_id, "2026-01-01") == [], name
    finally:
        set_language(was)
