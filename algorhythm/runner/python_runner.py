"""Runs a Python solution against its cases in a single subprocess."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from algorhythm.catalog.models import Problem, TestCase
from algorhythm.runner.harness import CaseResult, CaseStatus, RunResult

# Headroom over the per-case budget so SIGALRM gets a chance to fire first
# and produce a per-case TIMEOUT rather than an opaque whole-batch kill.
_BATCH_OVERHEAD_S = 5.0


def run_python(
    problem: Problem,
    solution_path: Path,
    cases: list[TestCase],
    *,
    timeout_s: float = 5.0,
) -> RunResult:
    job = {
        "solution_path": str(solution_path),
        "entry_point": problem.entry_point,
        "params": [asdict(p) for p in problem.params],
        "return_kind": problem.return_kind,
        "timeout_s": timeout_s,
        "cases": [
            {"id": c.id, "args": c.args, "expected": c.expected} for c in cases
        ],
    }

    batch_timeout = timeout_s * max(len(cases), 1) + _BATCH_OVERHEAD_S
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "algorhythm.runner._pyharness"],
            input=json.dumps(job),
            capture_output=True,
            text=True,
            timeout=batch_timeout,
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            cases=[
                CaseResult(id=c.id, status=CaseStatus.TIMEOUT, expected=c.expected)
                for c in cases
            ]
        )

    if completed.returncode != 0 or not completed.stdout.strip():
        detail = completed.stderr.strip() or "harness produced no output"
        return RunResult(compile_error=detail)

    payload = json.loads(completed.stdout)
    if "compile_error" in payload:
        return RunResult(compile_error=payload["compile_error"])

    return RunResult(
        cases=[
            CaseResult(
                id=r["id"],
                status=CaseStatus(r["status"]),
                expected=r["expected"],
                actual=r["actual"],
                error=r["error"],
                duration_ms=r["duration_ms"],
            )
            for r in payload["results"]
        ]
    )
