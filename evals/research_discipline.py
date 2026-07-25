#!/usr/bin/env python3
"""FORGE research-discipline eval — does research-FIRST beat answering from memory?

This locks in the 2026-07-24 A/B experiment as a re-runnable proof + a generic scorer.
The claim Forge makes (and this measured):

  EXTERNAL/current facts  -> research is STRICTLY better than memory (accuracy AND
                            run-to-run consistency).
  LOCAL facts (in-repo)   -> research is REDUNDANT (a capable model reads the code).
  JUDGMENT/recommendation -> research improves the *grounding* of the reasoning, not
                            necessarily the *conclusion* (blinded judges confirmed the
                            research-grounded rec, but the conclusion did not flip).

WHY A DATED SNAPSHOT: the version numbers below move (that is the whole point — memory
goes stale). The recorded fixtures below are the July-2026 measurement; a LIVE re-run
must refresh `key` from the cited source. The scorer is generic (answer vs a supplied
key), so the harness stays valid as the world's facts change.

Run:  python3 evals/research_discipline.py        # replay the recorded proof, exit!=0
                                                   # if it ever fails to reproduce
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MEASURED_ON = "2026-07-24"


@dataclass(frozen=True)
class Question:
    id: str
    kind: str          # "external" | "local" | "judgment"
    prompt: str
    source: str        # authoritative source to refresh the key from on a live run


QUESTIONS: list[Question] = [
    Question("python_latest", "external",
             "Latest stable Python release?", "https://endoflife.date/python"),
    Question("go_latest", "external",
             "Latest stable Go release?", "https://go.dev/doc/devel/release"),
    Question("rust_latest", "external",
             "Latest stable Rust release?", "https://blog.rust-lang.org/releases/latest/"),
]

# --- recorded 2026-07-24 ground truth (REFRESH on a live run) --------------------
KEY: dict[str, str] = {
    "python_latest": "3.14.6",
    "go_latest": "1.26.5",
    "rust_latest": "1.97.1",
}

# --- recorded answers from the experiment (the proof fixtures) -------------------
# Two memory-only runs (web forbidden) — note they DISAGREE with each other.
MEMORY_RUNS: list[dict[str, str]] = [
    {"python_latest": "3.13.1", "go_latest": "1.23.4", "rust_latest": "1.83.0"},
    {"python_latest": "3.14.1", "go_latest": "1.25.4", "rust_latest": "1.92.0"},
]
# Two must-search runs — identical to each other and correct.
SEARCH_RUNS: list[dict[str, str]] = [
    {"python_latest": "3.14.6", "go_latest": "1.26.5", "rust_latest": "1.97.1"},
    {"python_latest": "3.14.6", "go_latest": "1.26.5", "rust_latest": "1.97.1"},
]


def _norm(v: str) -> str:
    m = re.search(r"\d+(?:\.\d+){1,2}", v)
    return m.group(0) if m else v.strip()


def matches(answer: str, key: str) -> bool:
    """An answer counts as correct only if its version EXACTLY equals the key.
    (A right major.minor with a wrong patch is NOT correct — stale is stale.)"""
    return _norm(answer) == _norm(key)


def score(answers: dict[str, str], key: dict[str, str]) -> dict[str, object]:
    per = {qid: matches(answers.get(qid, ""), key[qid]) for qid in key}
    correct = sum(1 for ok in per.values() if ok)
    return {"per_item": per, "correct": correct, "total": len(key),
            "accuracy": correct / len(key) if key else 0.0}


def consistency(runs: list[dict[str, str]]) -> float:
    """Fraction of questions on which ALL runs gave the same normalized answer."""
    if not runs:
        return 0.0
    ids = runs[0].keys()
    agree = sum(1 for qid in ids
                if len({_norm(r.get(qid, "")) for r in runs}) == 1)
    return agree / len(ids)


@dataclass
class Report:
    memory_accuracy: float
    search_accuracy: float
    memory_consistency: float
    search_consistency: float
    lines: list[str] = field(default_factory=list)


def run() -> Report:
    mem = [score(r, KEY) for r in MEMORY_RUNS]
    sea = [score(r, KEY) for r in SEARCH_RUNS]
    mem_acc = sum(s["accuracy"] for s in mem) / len(mem)  # type: ignore[misc]
    sea_acc = sum(s["accuracy"] for s in sea) / len(sea)  # type: ignore[misc]
    rep = Report(mem_acc, sea_acc, consistency(MEMORY_RUNS), consistency(SEARCH_RUNS))
    rep.lines.append(f"FORGE research-discipline eval (measured {MEASURED_ON})")
    rep.lines.append(f"  memory   accuracy={mem_acc:.0%}  consistency={rep.memory_consistency:.0%}")
    rep.lines.append(f"  research accuracy={sea_acc:.0%}  consistency={rep.search_consistency:.0%}")
    return rep


def main() -> int:
    rep = run()
    for ln in rep.lines:
        print(ln)
    # The proof must reproduce: research strictly beats memory on both axes.
    ok = rep.search_accuracy > rep.memory_accuracy and \
        rep.search_consistency >= rep.memory_consistency
    print("verdict:", "OK — research beats memory" if ok else "FAIL — proof did not reproduce")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
