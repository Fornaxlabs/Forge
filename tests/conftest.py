"""Shared test isolation.

hooks/guard.py and traces/forge_trace.py resolve their run state from
FORGE_HOME (default: ./.forge). When the test suite runs inside a repo with a
LIVE governed run (e.g. Forge governing work on itself), that real
active_run.json — tool-call counts, blocker tallies, ceilings — would leak into
every test that doesn't set FORGE_HOME itself and flip guard verdicts.

Point FORGE_HOME at a fresh tmp dir per test so the suite is hermetic and never
reads or mutates the repo's real run state. Tests that need a specific
FORGE_HOME still win: their own monkeypatch.setenv runs after this fixture.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_forge_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "forge-home-isolated"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("FORGE_HOME", str(home))
