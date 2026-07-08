"""Unit tests for the FORGE memory CLI. Target: ≥80% coverage."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

# Load memory/forge_memory.py as a module without needing a package.
_MOD_PATH = Path(__file__).resolve().parent.parent / "memory" / "forge_memory.py"
_spec = importlib.util.spec_from_file_location("forge_memory", _MOD_PATH)
assert _spec and _spec.loader
fm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fm)


@pytest.fixture()
def conn():
    c = fm.connect(":memory:")
    fm.init(c)
    yield c
    c.close()


def test_add_search_roundtrip(conn):
    new_id = fm.add(
        conn,
        type="finding",
        topic="sql injection",
        content="unparameterized query in users.py",
        source="users.py:42",
    )
    assert new_id > 0
    rows = fm.search(conn, "injection")
    assert len(rows) == 1
    assert rows[0]["topic"] == "sql injection"


def test_fts_matches_content_not_just_topic(conn):
    fm.add(
        conn,
        type="finding",
        topic="auth",
        content="missing deny-by-default on the export route",
        source="t1",
    )
    # match on a word only present in content
    rows = fm.search(conn, "export")
    assert len(rows) == 1


def test_search_type_filter(conn):
    fm.add(conn, type="finding", topic="a", content="alpha token", source="s")
    fm.add(conn, type="decision", topic="b", content="beta token", source="s")
    rows = fm.search(conn, "token", type="decision")
    assert len(rows) == 1
    assert rows[0]["type"] == "decision"


def test_search_newest_first(conn, monkeypatch):
    monkeypatch.setattr(fm, "_now", lambda: "2026-01-01T00:00:00+00:00")
    fm.add(conn, type="finding", topic="old", content="shared word", source="s")
    monkeypatch.setattr(fm, "_now", lambda: "2026-06-01T00:00:00+00:00")
    fm.add(conn, type="finding", topic="new", content="shared word", source="s")
    rows = fm.search(conn, "shared")
    assert [r["topic"] for r in rows] == ["new", "old"]


def test_search_limit(conn):
    for i in range(5):
        fm.add(conn, type="finding", topic=f"t{i}", content="repeat", source="s")
    rows = fm.search(conn, "repeat", limit=2)
    assert len(rows) == 2


def test_add_rejects_bad_type(conn):
    with pytest.raises(ValueError):
        fm.add(conn, type="bogus", topic="t", content="c", source="s")


def test_add_rejects_empty_fields(conn):
    with pytest.raises(ValueError):
        fm.add(conn, type="finding", topic="  ", content="c", source="s")
    with pytest.raises(ValueError):
        fm.add(conn, type="finding", topic="t", content="c", source="  ")


def test_search_rejects_empty_query(conn):
    with pytest.raises(ValueError):
        fm.search(conn, "   ")


def test_curate_finds_duplicates(conn):
    for _ in range(2):
        fm.add(conn, type="finding", topic="dup", content="same", source="s")
    fm.add(conn, type="finding", topic="unique", content="other", source="s")
    result = fm.curate(conn)
    assert len(result["duplicates"]) == 2
    assert result["missing_source"] == []


def test_delete_keeps_fts_in_sync(conn):
    new_id = fm.add(conn, type="finding", topic="gone", content="vanish", source="s")
    conn.execute("DELETE FROM memories WHERE id = ?", (new_id,))
    conn.commit()
    assert fm.search(conn, "vanish") == []


def test_now_returns_iso_utc():
    ts = fm._now()
    assert ts.endswith("+00:00")


# ---- CLI (main) tests ----

def test_cli_init_add_search(tmp_path, capsys):
    db = str(tmp_path / "m.db")
    assert fm.main(["--db", db, "init"]) == 0
    assert fm.main([
        "--db", db, "add", "--type", "finding",
        "--topic", "cli topic", "--content", "cli content", "--source", "s",
    ]) == 0
    assert fm.main(["--db", db, "search", "cli"]) == 0
    out = capsys.readouterr().out
    assert "cli topic" in out


def test_cli_search_no_matches(tmp_path, capsys):
    db = str(tmp_path / "m.db")
    fm.main(["--db", db, "init"])
    fm.main(["--db", db, "search", "nothinghere"])
    assert "no matches" in capsys.readouterr().out


def test_cli_add_bad_type_returns_error(tmp_path, capsys):
    db = str(tmp_path / "m.db")
    fm.main(["--db", db, "init"])
    # argparse rejects invalid choice -> SystemExit(2)
    with pytest.raises(SystemExit):
        fm.main([
            "--db", db, "add", "--type", "bogus",
            "--topic", "t", "--content", "c", "--source", "s",
        ])


def test_cli_add_empty_content_returns_1(tmp_path):
    db = str(tmp_path / "m.db")
    fm.main(["--db", db, "init"])
    rc = fm.main([
        "--db", db, "add", "--type", "finding",
        "--topic", "t", "--content", "   ", "--source", "s",
    ])
    assert rc == 1


def test_cli_curate(tmp_path, capsys):
    db = str(tmp_path / "m.db")
    fm.main(["--db", db, "init"])
    for _ in range(2):
        fm.main([
            "--db", db, "add", "--type", "finding",
            "--topic", "dup", "--content", "same", "--source", "s",
        ])
    fm.main(["--db", db, "curate"])
    assert "duplicates: 2" in capsys.readouterr().out


def test_connect_creates_parent_dir(tmp_path):
    db = str(tmp_path / "nested" / "dir" / "m.db")
    c = fm.connect(db)
    fm.init(c)
    c.close()
    assert os.path.exists(db)
