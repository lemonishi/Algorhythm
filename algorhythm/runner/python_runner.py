"""Runs a Python solution against its cases in a single subprocess."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
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
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as handle:
        results_path = Path(handle.name)

    job = {
        "results_path": str(results_path),
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
    stderr = ""
    # The unlink covers the whole body, not just the read: an OSError raised
    # by subprocess.run itself (no file descriptors left, say) is not a
    # TimeoutExpired, so it escapes — and used to take the results file with
    # it, leaking one per failed rep.
    try:
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "algorhythm.runner._pyharness"],
                input=json.dumps(job),
                capture_output=True,
                text=True,
                timeout=batch_timeout,
            )
            stderr = completed.stderr
            crashed = completed.returncode != 0
        except subprocess.TimeoutExpired:
            crashed = False

        try:
            lines = results_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []

        payloads = [json.loads(line) for line in lines if line.strip()]

        for payload in payloads:
            if "compile_error" in payload:
                return RunResult(compile_error=payload["compile_error"])

        if not payloads and crashed:
            return RunResult(
                compile_error=stderr.strip() or "harness produced no output"
            )

        return _collect(payloads, cases)
    finally:
        results_path.unlink(missing_ok=True)


def _collect(payloads: list[dict], cases: list[TestCase]) -> RunResult:
    """Pair reported results with the cases that asked for them.

    A case with no result never reported. The FIRST such case is the one
    that hung — the harness flushes in order, so everything after it simply
    never got to run.
    """
    reported = {p["id"]: p for p in payloads}
    results: list[CaseResult] = []
    hang_assigned = False

    for case in cases:
        payload = reported.get(case.id)
        if payload is not None:
            results.append(
                CaseResult(
                    id=payload["id"],
                    status=CaseStatus(payload["status"]),
                    expected=payload["expected"],
                    actual=payload["actual"],
                    error=payload["error"],
                    duration_ms=payload["duration_ms"],
                )
            )
        elif not hang_assigned:
            hang_assigned = True
            results.append(
                CaseResult(
                    id=case.id,
                    status=CaseStatus.TIMEOUT,
                    expected=case.expected,
                    error="exceeded the batch time budget",
                )
            )
        else:
            results.append(
                CaseResult(
                    id=case.id,
                    status=CaseStatus.ERROR,
                    expected=case.expected,
                    error="no result reported (an earlier case aborted the run)",
                )
            )

    return RunResult(cases=results)


# A value no real solution can return, so every probe reports FAIL and we
# read `actual` as the reference's output.
_ORACLE_SENTINEL = "__algorhythm_oracle_probe__"


def evaluate_python(
    problem: Problem,
    solution_path: Path,
    arg_sets: list[dict],
    *,
    timeout_s: float = 5.0,
) -> RunResult:
    """Run a solution over argument sets purely to observe its outputs.

    Used to derive expected values from a reference solution. Read
    `case.actual`; `case.status` is FAIL by construction and carries no
    meaning here beyond 'it ran'.
    """
    cases = [
        TestCase(
            id=f"probe-{index}",
            args=args,
            expected=_ORACLE_SENTINEL,
            source="oracle",
        )
        for index, args in enumerate(arg_sets)
    ]
    return run_python(problem, solution_path, cases, timeout_s=timeout_s)
