"""Tests for evals/research_discipline.py — the research-first proof + scorer."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_P = Path(__file__).resolve().parent.parent / "evals" / "research_discipline.py"
_spec = importlib.util.spec_from_file_location("research_discipline", _P)
assert _spec and _spec.loader
rd = importlib.util.module_from_spec(_spec)
# register before exec: the module's dataclasses + `from __future__ import annotations`
# make dataclass resolve annotations via sys.modules[__name__] at class-creation time
sys.modules[_spec.name] = rd
_spec.loader.exec_module(rd)


def test_matches_exact_only():
    assert rd.matches("3.14.6", "3.14.6") is True
    assert rd.matches("Python 3.14.6 (June 2026)", "3.14.6") is True  # extracts version
    assert rd.matches("3.14.1", "3.14.6") is False  # right line, wrong patch = stale
    assert rd.matches("", "3.14.6") is False


def test_score_counts_correct():
    s = rd.score(
        {"python_latest": "3.14.6", "go_latest": "1.26.5", "rust_latest": "1.97.1"},
        rd.KEY,
    )
    assert s["correct"] == 3
    assert s["accuracy"] == 1.0


def test_memory_runs_are_wrong_and_inconsistent():
    # the recorded proof: memory answered wrong and disagreed with itself
    accs = [rd.score(r, rd.KEY)["accuracy"] for r in rd.MEMORY_RUNS]
    assert max(accs) < 1.0  # neither memory run was fully correct
    assert rd.consistency(rd.MEMORY_RUNS) < 1.0  # the two runs disagreed


def test_search_runs_are_correct_and_consistent():
    accs = [rd.score(r, rd.KEY)["accuracy"] for r in rd.SEARCH_RUNS]
    assert min(accs) == 1.0  # every search run fully correct
    assert rd.consistency(rd.SEARCH_RUNS) == 1.0  # and identical to each other


def test_proof_reproduces():
    rep = rd.run()
    assert rep.search_accuracy > rep.memory_accuracy
    assert rep.search_consistency >= rep.memory_consistency


def test_main_exits_ok():
    assert rd.main() == 0
