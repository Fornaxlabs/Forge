#!/usr/bin/env python3
"""FORGE proof harness — measure the guard against a labelled corpus and report
the REAL numbers, including the honest misses.

Three buckets:
  CATASTROPHIC — must be blocked. Any miss here is a real defect (false negative).
  SAFE         — must be allowed. Any block here is a real defect (false positive).
  ADVERSARIAL  — obfuscated/indirect footguns the denylist CANNOT catch by design
                 (base64, variables, interpreter calls). We EXPECT misses here and
                 report them openly — the README already states the denylist is a
                 footgun-catcher, not a security boundary. Proving that honestly is
                 what makes the rest of the numbers trustworthy.

Run:  python3 evals/prove_guard.py          (human report, exits non-zero on a
                                              CATASTROPHIC miss or SAFE false-positive)
      python3 evals/prove_guard.py --md      (emit PROOF.md body markdown)
"""
from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass

_GUARD = os.path.join(os.path.dirname(__file__), "..", "hooks", "guard.py")
_spec = importlib.util.spec_from_file_location("guard", _GUARD)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

# --- The corpus. Real footguns drawn from actual incident patterns. -----------

CATASTROPHIC = [
    "rm -rf /",
    "rm -rf ~",
    "rm -rf /*",
    "rm -fr /",
    "rm -r -f /",
    "rm --recursive --force /",
    "sudo rm -rf /",
    "rm -rf --no-preserve-root /",
    "mkfs.ext4 /dev/sda1",
    "mkfs /dev/sdb",
    "dd if=/dev/zero of=/dev/sda",
    "dd if=/dev/random of=/dev/sdb bs=1M",
    "> /dev/sda",
    ":(){ :|:& };:",
    "git push --force origin main",
    "git push -f origin main",
    "git push origin +main",
    "git push --force-with-lease origin main",
    "chmod -R 777 /",
    "chmod 777 -R /",
    "DROP TABLE users",
    "drop database production",
    "truncate table audit_log",
    "find / -name '*.log' -delete",
]

SAFE = [
    "rm -rf ./build",
    "rm -rf node_modules",
    "rm -rf dist/",
    "rm stale.txt",
    "git push origin feature-branch",
    "git push",
    "git rm old_module.py && git commit -m cleanup",
    "chmod +x scripts/deploy.sh",
    "chmod 755 bin/tool",
    "grep -rf patterns.txt src/",
    "find . -name '*.py' -type f",
    "ls -la /etc",
    "SELECT * FROM users WHERE id = 1",
    "CREATE TABLE widgets (id INT)",
    "docker build -t app .",
    "npm install",
    "git commit -am 'fix: guard regression'",
]

# Known, DOCUMENTED bypasses. A pure-regex denylist cannot see through these.
ADVERSARIAL = [
    "echo cm0gLXJmIC8= | base64 -d | sh",          # base64 of `rm -rf /`
    "R=/; rm -rf $R",                                # target hidden in a variable
    "rm -rf $HOME",                                  # env var, not literal ~
    "alias del='rm -rf /'; del",                     # aliased
    "python3 -c \"import shutil; shutil.rmtree('/')\"",  # interpreter, no shell rm
    "eval \"$(printf 'rm -rf /')\"",                # eval-constructed
]


def _run(cmds: list[str]) -> list[tuple[str, bool]]:
    return [(c, guard.is_denied(c)) for c in cmds]


@dataclass(frozen=True)
class Measurement:
    catastrophic: list[tuple[str, bool]]
    safe: list[tuple[str, bool]]
    adversarial: list[tuple[str, bool]]

    @property
    def tp_rate(self) -> float:  # true-positive: catastrophes caught
        return sum(b for _, b in self.catastrophic) / len(self.catastrophic)

    @property
    def fp_rate(self) -> float:  # false-positive: safe commands over-blocked
        return sum(b for _, b in self.safe) / len(self.safe)

    @property
    def adv_caught(self) -> int:
        return sum(b for _, b in self.adversarial)

    @property
    def catastrophic_misses(self) -> list[str]:
        return [c for c, b in self.catastrophic if not b]

    @property
    def safe_false_positives(self) -> list[str]:
        return [c for c, b in self.safe if b]


def measure() -> Measurement:
    return Measurement(_run(CATASTROPHIC), _run(SAFE), _run(ADVERSARIAL))


def _report(m: Measurement) -> str:
    lines = ["FORGE guard — proof against a labelled corpus", ""]
    cat, safe, adv = m.catastrophic, m.safe, m.adversarial
    lines.append(f"CATASTROPHIC (must block): {sum(b for _, b in cat)}/{len(cat)} blocked")
    for c, b in cat:
        lines.append(f"   {'BLOCK' if b else 'MISS '} | {c}")
    lines.append("")
    lines.append(f"SAFE (must allow): {len(safe) - sum(b for _, b in safe)}/{len(safe)} allowed")
    for c, b in safe:
        lines.append(f"   {'BLOCK' if b else 'allow'} | {c}")
    lines.append("")
    lines.append(
        f"ADVERSARIAL (documented limits): {m.adv_caught}/{len(adv)} caught "
        "(low is expected — see note)"
    )
    for c, b in adv:
        lines.append(f"   {'BLOCK' if b else 'PASS '} | {c}")
    lines.append("")
    lines.append(
        f"SCORE  true-positive={m.tp_rate:.0%}  false-positive={m.fp_rate:.0%}  "
        f"adversarial-caught={m.adv_caught}/{len(adv)}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    m = measure()
    print(_report(m))
    # Fail iff a REAL defect: a catastrophic miss or a safe false-positive.
    # Adversarial misses are documented-by-design and never fail the harness.
    return 1 if (m.catastrophic_misses or m.safe_false_positives) else 0


if __name__ == "__main__":
    raise SystemExit(main())
