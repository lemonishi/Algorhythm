"""Executed inside the solution subprocess. Reads a job on stdin, writes
one JSON object per case to the file named by `results_path`, flushing
after each.

Two reasons it is a file and not stdout. First, solutions print while
debugging, and a stray `print()` on a shared channel corrupts the
protocol. Second, flushing per case means a batch-timeout kill still
leaves the results of every case that already finished — the caller can
then attribute the hang to the exact case that never reported.

Run as `python -m algorhythm.runner._pyharness` so the package is importable.

Per-case timeouts use SIGALRM, which interrupts Python bytecode. A tight
loop inside a C extension will not be interrupted — the caller's subprocess
timeout is the backstop for that.
"""

from __future__ import annotations

import json
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from algorhythm.codecs.leetcode_types import decode, encode


class _Timeout(Exception):
    pass


def _on_alarm(signum, frame):  # noqa: ANN001, ARG001
    raise _Timeout()


def _load_solution(path: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location("_solution", path)
    module = importlib.util.module_from_spec(spec)
    _inject_leetcode_globals(module)
    spec.loader.exec_module(module)
    return module


def _inject_leetcode_globals(module) -> None:
    """LeetCode stubs reference TreeNode, ListNode, Optional and List without
    importing them. Supply them so a pasted stub runs unmodified."""
    from typing import Any as _Any
    from typing import Dict, List, Optional, Set, Tuple

    from algorhythm.codecs.leetcode_types import ListNode, TreeNode

    for name, value in {
        "TreeNode": TreeNode,
        "ListNode": ListNode,
        "Optional": Optional,
        "List": List,
        "Dict": Dict,
        "Set": Set,
        "Tuple": Tuple,
        "Any": _Any,
    }.items():
        setattr(module, name, value)


def main() -> int:
    job = json.load(sys.stdin)
    results_path = job["results_path"]
    solution_path = job["solution_path"]
    entry_point = job["entry_point"]
    params = job["params"]
    return_kind = job["return_kind"]
    timeout_s = float(job["timeout_s"])

    sink = open(results_path, "w", encoding="utf-8")

    def write(payload: dict[str, Any]) -> None:
        json.dump(payload, sink, default=str)
        sink.write("\n")
        sink.flush()

    try:
        module = _load_solution(solution_path)
        solution_cls = getattr(module, "Solution")
        instance = solution_cls()
        method = getattr(instance, entry_point)
    except Exception:
        write({"compile_error": traceback.format_exc(limit=3)})
        sink.close()
        return 0

    signal.signal(signal.SIGALRM, _on_alarm)

    for case in job["cases"]:
        kwargs = {
            spec["name"]: decode(case["args"][spec["name"]], spec["kind"])
            for spec in params
        }
        started = time.perf_counter()
        signal.setitimer(signal.ITIMER_REAL, timeout_s)
        try:
            raw = method(**kwargs)
            actual = encode(raw, return_kind)
            status = "pass" if actual == case["expected"] else "fail"
            error = None
        except _Timeout:
            status, actual, error = "timeout", None, f"exceeded {timeout_s}s"
        except Exception:
            status, actual, error = "error", None, traceback.format_exc(limit=3)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)

        write(
            {
                "id": case["id"],
                "status": status,
                "expected": case["expected"],
                "actual": actual,
                "error": error,
                "duration_ms": int((time.perf_counter() - started) * 1000),
            }
        )

    sink.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
