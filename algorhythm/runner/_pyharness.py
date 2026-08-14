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

from algorhythm.codecs.leetcode_types import decode, encode, equal


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
    """Seed the module namespace the way LeetCode's judge does.

    Solutions written for LeetCode use `TreeNode`, `List`, `collections`,
    `math` and `deque` without importing any of them, because the judge
    supplies them. Every reference solution we import is written against
    that judge, and so is anything the user pastes in from a past attempt.

    Without this the solution raises NameError on its first case, which the
    reader sees as their answer being wrong rather than as a missing import.

    These are defaults, not overrides: they land before the module executes,
    so an explicit `import math` in the solution simply rebinds the name.
    """
    import bisect
    import collections
    import functools
    import heapq
    import itertools
    import math
    import operator
    import random
    import re as _re
    import string
    from collections import Counter, OrderedDict, defaultdict, deque
    from heapq import (
        heapify,
        heappop,
        heappush,
        heappushpop,
        heapreplace,
        nlargest,
        nsmallest,
    )
    from typing import Any as _Any
    from typing import Dict, List, Optional, Set, Tuple

    from algorhythm.codecs.leetcode_types import ListNode, Node, TreeNode

    for name, value in {
        "TreeNode": TreeNode,
        "ListNode": ListNode,
        "Node": Node,
        "Optional": Optional,
        "List": List,
        "Dict": Dict,
        "Set": Set,
        "Tuple": Tuple,
        "Any": _Any,
        "bisect": bisect,
        "collections": collections,
        "functools": functools,
        "heapq": heapq,
        "itertools": itertools,
        "math": math,
        "operator": operator,
        "random": random,
        "re": _re,
        "string": string,
        "Counter": Counter,
        "OrderedDict": OrderedDict,
        "defaultdict": defaultdict,
        "deque": deque,
        # LeetCode's judge does `from heapq import *`, so references written
        # against it call these bare.
        "heapify": heapify,
        "heappop": heappop,
        "heappush": heappush,
        "heappushpop": heappushpop,
        "heapreplace": heapreplace,
        "nlargest": nlargest,
        "nsmallest": nsmallest,
    }.items():
        setattr(module, name, value)


def main() -> int:
    job = json.load(sys.stdin)
    results_path = job["results_path"]
    solution_path = job["solution_path"]
    entry_point = job["entry_point"]
    params = job["params"]
    return_kind = job["return_kind"]
    comparison = job.get("comparison", "exact")
    answer_param = job.get("answer_param")
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
        # Positional, not keyword. The stub and the reference can disagree
        # about a parameter's NAME — LeetCode renamed partition-labels' `S`
        # to `s` and neetcode's reference still says `S` — but never about
        # their order, and a keyword call raises TypeError on the mismatch,
        # which reads as the reference being broken.
        args = [
            decode(case["args"][spec["name"]], spec["kind"]) for spec in params
        ]
        started = time.perf_counter()
        signal.setitimer(signal.ITIMER_REAL, timeout_s)
        try:
            raw = method(*args)
            if answer_param is None:
                actual = encode(raw, return_kind)
            else:
                # The method returned nothing and mutated an argument; that
                # argument is the answer. It is read back from `args`, which
                # still references the object the solution modified.
                index = next(
                    i for i, spec in enumerate(params)
                    if spec["name"] == answer_param
                )
                actual = encode(args[index], params[index]["kind"])

            # Through JSON before comparing, so the value judged is exactly
            # the value reported. A solution returning tuples is the common
            # case: JSON has no tuple, so `actual` arrives as a list, and
            # comparing the tuple instead fails a correct answer while
            # printing an `actual` identical to `expected` — a mismatch with
            # nothing on screen to explain it.
            actual = json.loads(json.dumps(actual, default=str))
            # `actual` is reported unnormalized: the reader compares it with
            # the expected value by eye, and silently reordering their
            # output would make a genuine mismatch harder to read.
            status = (
                "pass" if equal(actual, case["expected"], comparison) else "fail"
            )
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
