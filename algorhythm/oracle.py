"""Edge-case generation using the reference solution as an oracle.

Two ideas do the work here:

  1. Perturb the *example* input rather than inventing inputs from nothing.
     The example is known to be in-contract, so variations of it usually are
     too, and its shape tells us what the parameter actually is.

  2. Vary one parameter at a time. A cartesian product over parameters
     explodes; one-at-a-time stays linear and still covers each parameter's
     edges.

Any candidate the reference rejects — by raising or hanging — is dropped
rather than recorded, on the reasoning that it is out of contract.
"""

from __future__ import annotations

import json
from itertools import zip_longest
from pathlib import Path
from typing import Any

from algorhythm.catalog.models import Problem, TestCase
from algorhythm.runner.harness import CaseStatus
from algorhythm.runner.python_runner import evaluate_python

# Cases kept per problem, and how many candidates we're willing to run
# through the reference to find them. The pool is larger because the
# reference rejects out-of-contract candidates, and they all run in one
# batched subprocess, so a wider pool costs almost nothing.
_MAX_CASES = 8
_MAX_CANDIDATES = 24


def _int_list_perturbations(value: list[int]) -> list[list[int]]:
    first = value[0] if value else 0
    return [
        [],
        [first],
        [first] * 3,
        sorted(value),
        list(reversed(value)),
        [-abs(v) for v in value],
        value + value,
    ]


def perturbations(value: Any, kind: str) -> list[Any]:
    """Edge variants of a single argument. Never includes `value` itself."""
    return [v for v in _raw_perturbations(value, kind) if v != value]


def _raw_perturbations(value: Any, kind: str) -> list[Any]:
    if kind == "tree":
        return [[], [1], [1, 2, None, 3], [1, None, 2, None, 3]]
    if kind == "linked_list":
        return [[], [1], [1, 1, 1]]
    if kind == "grid":
        # Cell values are borrowed from the grid we were given rather than
        # written as literals. number-of-islands takes a grid of "1"/"0"
        # STRINGS, and a hardcoded `[[1]]` is an int grid — which the C++
        # codegen then declares `vector<vector<int>>` and cannot bind to the
        # signature's `vector<vector<char>>&`.
        rows = value or []
        cells = [cell for row in rows for cell in row]
        if not cells:
            return []
        distinct: list[Any] = []
        for cell in cells:
            if cell not in distinct:
                distinct.append(cell)
        return [[[cell]] for cell in distinct[:2]] + [[row[:1] for row in rows]]

    if isinstance(value, bool):
        return [not value]
    if isinstance(value, int):
        return [0, 1, -1, -abs(value) if value else -1]
    if isinstance(value, str):
        first = value[0] if value else "a"
        return ["", first, first * 3, value[::-1]]
    if isinstance(value, list):
        if value and all(isinstance(v, list) for v in value):
            return [[[1]], [value[0]]]
        if all(isinstance(v, int) and not isinstance(v, bool) for v in value):
            return _int_list_perturbations(value)
        if all(isinstance(v, str) for v in value):
            return [[], value[:1], value + value]
    return []


def _key(args: dict[str, Any]) -> str:
    return json.dumps(args, sort_keys=True, default=str)


def candidate_args(problem: Problem, seed_args: dict[str, Any]) -> list[dict[str, Any]]:
    """Argument sets that differ from `seed_args` in exactly one parameter.

    Round-robins across parameters rather than exhausting each in turn: the
    caller truncates this list, and parameter-major order would let the
    first parameter's variants consume the whole budget, leaving later
    parameters with no coverage at all.
    """
    per_parameter: list[list[dict[str, Any]]] = []
    for spec in problem.params:
        if spec.name not in seed_args:
            continue
        variants = []
        for variant in perturbations(seed_args[spec.name], spec.kind):
            candidate = dict(seed_args)
            candidate[spec.name] = variant
            variants.append(candidate)
        per_parameter.append(variants)

    out: list[dict[str, Any]] = []
    seen = {_key(seed_args)}
    for row in zip_longest(*per_parameter):
        for candidate in row:
            if candidate is None:
                continue
            fingerprint = _key(candidate)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            out.append(candidate)

    return out


def generate_oracle_cases(
    problem: Problem,
    reference_path: Path,
    seed_args: dict[str, Any],
    *,
    timeout_s: float = 5.0,
) -> list[TestCase]:
    """Derive test cases whose expected outputs come from the reference.

    Returns an empty list if the reference will not run — a broken reference
    must never silently produce authoritative-looking expectations.
    """
    candidates = candidate_args(problem, seed_args)[:_MAX_CANDIDATES]
    if not candidates:
        return []

    result = evaluate_python(problem, reference_path, candidates, timeout_s=timeout_s)
    if result.compile_error:
        return []

    # Keep the first _MAX_CASES survivors rather than truncating the pool
    # up front: candidates the reference rejects must not consume the budget,
    # or a problem whose early candidates are all out of contract ends up
    # with no generated cases at all.
    cases: list[TestCase] = []
    for case_result, args in zip(result.cases, candidates):
        if len(cases) >= _MAX_CASES:
            break
        if case_result.status in (CaseStatus.ERROR, CaseStatus.TIMEOUT):
            continue  # out of contract for this problem
        if case_result.actual is None:
            # The reference fell off the end of a function rather than
            # returning — neetcode's two-sum does exactly this when no pair
            # sums to the target. Recording `null` would then fail a correct
            # solution that returns `[]`, which is what the signature says.
            # `None` never reaches here for tree, list, or graph returns:
            # those encode an absent value as `[]`.
            continue
        cases.append(
            TestCase(
                id=f"oracle-{len(cases) + 1}",
                args=args,
                expected=case_result.actual,
                source="oracle",
            )
        )
    return cases
