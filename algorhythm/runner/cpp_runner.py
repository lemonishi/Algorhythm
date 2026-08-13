"""C++ execution with a content-hashed binary cache.

C++ has no standard JSON, so rather than parsing at runtime we generate a
main.cpp with the cases as C++ literals. Both sides reduce values to the
same canonical string, making comparison a string equality check.

The generated harness flushes after each case, so a whole-batch timeout
still tells us exactly which case hung.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from algorhythm import config
from algorhythm.catalog.models import Problem, TestCase
from algorhythm.runner.harness import CaseResult, CaseStatus, RunResult

CXX = "clang++"
CXX_FLAGS = ["-std=c++17", "-O0", "-w"]  # -O0: inputs are tiny, compile speed wins
_TYPES_HEADER = Path(__file__).parent / "cpp" / "leetcode_types.h"

_CPP_TYPE = {
    "tree": "TreeNode*",
    "linked_list": "ListNode*",
}


class CodegenError(Exception):
    pass


def canonical(value: Any) -> str:
    """The comparison format. Must match repr() in leetcode_types.h."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.5f}"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical(v) for v in value) + "]"
    raise CodegenError(f"cannot express {type(value).__name__} in the canonical form")


def _literal(value: Any, kind: str) -> tuple[str, str]:
    """Return (c++ declaration type, c++ initializer expression)."""
    if kind in _CPP_TYPE:
        items = ",".join("NUL" if v is None else str(v) for v in (value or []))
        builder = "buildTree" if kind == "tree" else "buildList"
        return _CPP_TYPE[kind], f"{builder}({{{items}}})"

    if isinstance(value, bool):
        return "bool", "true" if value else "false"
    if isinstance(value, int):
        return "int", str(value)
    if isinstance(value, float):
        return "double", repr(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return "string", f'"{escaped}"'
    if isinstance(value, list):
        if not value:
            return "vector<int>", "{}"
        if all(isinstance(v, list) for v in value):
            rows = ",".join(
                "{" + ",".join(str(x) for x in row) + "}" for row in value
            )
            return "vector<vector<int>>", "{" + rows + "}"
        if all(isinstance(v, str) for v in value):
            items = ",".join(f'"{v}"' for v in value)
            return "vector<string>", "{" + items + "}"
        if all(isinstance(v, bool) for v in value):
            items = ",".join("true" if v else "false" for v in value)
            return "vector<bool>", "{" + items + "}"
        if all(isinstance(v, int) for v in value):
            return "vector<int>", "{" + ",".join(str(v) for v in value) + "}"

    raise CodegenError(f"cannot express {value!r} as a C++ literal")


def _generate_main(problem: Problem, solution_path: Path, cases: list[TestCase]) -> str:
    blocks: list[str] = []
    for index, case in enumerate(cases):
        lines = [f"  {{ // {case.id}"]
        arg_names = []
        for spec in problem.params:
            cpp_type, initializer = _literal(case.args[spec.name], spec.kind)
            var = f"arg{index}_{spec.name}"
            lines.append(f"    {cpp_type} {var} = {initializer};")
            arg_names.append(var)
        call = f"solution.{problem.entry_point}({', '.join(arg_names)})"
        expected = canonical(case.expected).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f"    string expected = \"{expected}\";")
        lines.append(f"    string actual = repr({call});")
        lines.append(
            f'    cout << "{case.id}\\t" '
            '<< (actual == expected ? "pass" : "fail") '
            '<< "\\t" << actual << "\\n" << flush;'
        )
        lines.append("  }")
        blocks.append("\n".join(lines))

    return "\n".join(
        [
            f'#include "{_TYPES_HEADER}"',
            f'#include "{solution_path}"',
            "",
            "int main() {",
            "  Solution solution;",
            *blocks,
            "  return 0;",
            "}",
            "",
        ]
    )


def _cache_key(main_source: str) -> str:
    digest = hashlib.sha256()
    digest.update(main_source.encode())
    digest.update(_TYPES_HEADER.read_bytes())
    digest.update(" ".join([CXX, *CXX_FLAGS]).encode())
    return digest.hexdigest()[:16]


def run_cpp(
    problem: Problem,
    solution_path: Path,
    cases: list[TestCase],
    *,
    timeout_s: float = 5.0,
    cache_root: Path | None = None,
) -> RunResult:
    if not cases:
        return RunResult(cases=[])

    root = (cache_root or config.cache_dir()) / "cpp"
    root.mkdir(parents=True, exist_ok=True)

    main_source = _generate_main(problem, solution_path, cases)
    # The solution's own bytes are part of the identity of the binary.
    key = _cache_key(main_source + solution_path.read_text())
    binary = root / key

    if not binary.exists():
        main_path = root / f"{key}.cpp"
        main_path.write_text(main_source)
        compiled = subprocess.run(
            [CXX, *CXX_FLAGS, "-o", str(binary), str(main_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        main_path.unlink(missing_ok=True)
        if compiled.returncode != 0:
            binary.unlink(missing_ok=True)
            return RunResult(compile_error=compiled.stderr.strip())

    batch_timeout = timeout_s * len(cases) + 5.0
    try:
        completed = subprocess.run(
            [str(binary)], capture_output=True, text=True, timeout=batch_timeout
        )
        stdout = completed.stdout
        timed_out = False
    except subprocess.TimeoutExpired as expired:
        raw = expired.output or b""
        stdout = raw.decode() if isinstance(raw, bytes) else raw
        timed_out = True

    return _parse_output(stdout, cases, timed_out)


def _parse_output(
    stdout: str, cases: list[TestCase], timed_out: bool
) -> RunResult:
    reported: dict[str, tuple[str, str]] = {}
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            reported[parts[0]] = (parts[1], parts[2])

    results: list[CaseResult] = []
    hang_assigned = False
    for case in cases:
        expected = canonical(case.expected)
        if case.id in reported:
            status_text, actual = reported[case.id]
            results.append(
                CaseResult(
                    id=case.id,
                    status=CaseStatus(status_text),
                    expected=expected,
                    actual=actual,
                )
            )
            continue

        # Unreported. The first unreported case is the one that hung; any
        # after it never got the chance to run.
        if timed_out and not hang_assigned:
            hang_assigned = True
            results.append(
                CaseResult(
                    id=case.id,
                    status=CaseStatus.TIMEOUT,
                    expected=expected,
                    error="exceeded the time budget",
                )
            )
        else:
            results.append(
                CaseResult(
                    id=case.id,
                    status=CaseStatus.ERROR,
                    expected=expected,
                    error="no result reported (earlier case aborted the run)",
                )
            )

    return RunResult(cases=results)
