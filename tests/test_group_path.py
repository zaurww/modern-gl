"""The groups a directory element is in — one rule for the directory and the stock
(«Долг» 14): outermost first, and a broken chain of parents never loops."""

from __future__ import annotations

from modern_gl.application.common import group_path

NODES = {1: ("Avadanlıq", None), 2: ("Kabellər", 1), 3: ("HDMI 2 m", 2)}


def test_the_path_is_outermost_first():
    assert group_path(NODES[3][1], NODES.get) == "Avadanlıq / Kabellər"
    assert group_path(NODES[1][1], NODES.get) == ""
    assert group_path(99, NODES.get) == ""  # a parent not known: no path


def test_a_cycle_of_parents_stops():
    looped = {1: ("A", 2), 2: ("B", 1)}
    assert group_path(1, looped.get) == "B / A"


def test_the_catalog_and_the_stock_name_the_same_path(ledger, conn):
    from modern_gl.application.catalog import Catalog
    from modern_gl.reporting.inventory.stock import group_paths

    cid = ledger.create_company("Группы")
    kind = ledger.add_subconto_kind(cid, "item", "Товары")
    outer = ledger.add_subconto_value(cid, kind, "Avadanlıq", is_group=True)
    inner = ledger.add_subconto_value(cid, kind, "Kabellər", is_group=True, parent_id=outer)
    item = ledger.add_subconto_value(cid, kind, "HDMI 2 m", parent_id=inner)
    assert Catalog(conn, cid).group_path(item) == "Avadanlıq / Kabellər"
    assert group_paths(conn, cid)[item] == "Avadanlıq / Kabellər"
