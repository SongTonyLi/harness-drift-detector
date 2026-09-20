"""Run the repository gates with bounded concurrency and attributable output.

    python scripts/gates.py pre-push          # what the git pre-push hook runs
    python scripts/gates.py ci                # everything CI runs
    python scripts/gates.py ci --only tests   # one gate by id

HDD_GATE_CONCURRENCY caps the worker count (default: min(4, CPUs)).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


@dataclass(frozen=True)
class Gate:
    id: str
    args: list[str]


GATES: dict[str, Gate] = {
    "layering": Gate("layering", [PY, "scripts/verify_layering.py"]),
    "agent-notes": Gate("agent-notes", [PY, "scripts/verify_agent_notes.py"]),
    "secrets": Gate("secrets", [PY, "scripts/verify_no_secrets.py"]),
    "ruff-check": Gate("ruff-check", [PY, "-m", "ruff", "check", "."]),
    "ruff-format": Gate("ruff-format", [PY, "-m", "ruff", "format", "--check", "."]),
    "tests": Gate("tests", [PY, "-m", "pytest", "-q", "-m", "not live"]),
    "build": Gate("build", ["uv", "build", "--no-progress", "-q"]),
}
MODES: dict[str, list[str]] = {
    "pre-push": ["layering", "agent-notes", "secrets", "ruff-check", "ruff-format", "tests"],
    "ci": ["layering", "agent-notes", "secrets", "ruff-check", "ruff-format", "tests", "build"],
}


@dataclass(frozen=True)
class Result:
    gate: Gate
    returncode: int
    seconds: float
    output: str


def run(gate: Gate) -> Result:
    started = time.perf_counter()
    proc = subprocess.run(gate.args, cwd=ROOT, capture_output=True, text=True)
    return Result(gate, proc.returncode, time.perf_counter() - started, proc.stdout + proc.stderr)


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in MODES:
        print(__doc__)
        return 2
    ids = MODES[argv[0]]
    if len(argv) == 3 and argv[1] == "--only":
        ids = [argv[2]]
    workers = int(os.environ.get("HDD_GATE_CONCURRENCY", min(4, os.cpu_count() or 1)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(run, (GATES[i] for i in ids)))
    failed = [r for r in results if r.returncode != 0]
    for result in results:
        status = "ok  " if result.returncode == 0 else "FAIL"
        print(f"[{status}] {result.gate.id:<12} {result.seconds:6.1f}s")
    for result in failed:
        print(
            f"\n===== {result.gate.id} ({' '.join(result.gate.args)}) =====\n"
            f"{result.output.rstrip()}"
        )
    print(f"\ngates: {len(results) - len(failed)}/{len(results)} passed ({argv[0]}).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
