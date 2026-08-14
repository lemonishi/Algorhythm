from datetime import datetime, timezone

import pytest

from algorhythm.catalog.models import ParamSpec, Problem, TestCase
from algorhythm.runner.harness import CaseStatus
from algorhythm.runner.python_runner import _collect, run_python


def problem(entry_point="addTwo", params=None, return_kind="raw") -> Problem:
    return Problem(
        slug="fixture",
        number=1,
        title="Fixture",
        difficulty="Easy",
        topics=[],
        companies=[],
        url="",
        statement_md="",
        constraints=[],
        examples=[],
        params=params or [ParamSpec("a"), ParamSpec("b")],
        return_kind=return_kind,
        entry_point=entry_point,
        fetched_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )


def write(tmp_path, source: str):
    path = tmp_path / "solution.py"
    path.write_text(source)
    return path


CORRECT = """
class Solution:
    def addTwo(self, a, b):
        return a + b
"""

WRONG = """
class Solution:
    def addTwo(self, a, b):
        return a * b
"""

RAISES = """
class Solution:
    def addTwo(self, a, b):
        raise ValueError("boom")
"""

HANGS = """
class Solution:
    def addTwo(self, a, b):
        while True:
            pass
"""

SYNTAX_ERROR = "class Solution:\n    def addTwo(self a b):\n"


def cases():
    return [
        TestCase(id="c1", args={"a": 1, "b": 2}, expected=3, source="example"),
        TestCase(id="c2", args={"a": 10, "b": 5}, expected=15, source="oracle"),
    ]


def test_correct_solution_passes_every_case(tmp_path):
    result = run_python(problem(), write(tmp_path, CORRECT), cases())
    assert result.ok
    assert result.passed == 2
    assert result.total == 2


def test_wrong_solution_reports_each_failure(tmp_path):
    result = run_python(problem(), write(tmp_path, WRONG), cases())
    assert not result.ok
    assert result.passed == 0
    assert all(c.status is CaseStatus.FAIL for c in result.cases)


def test_failure_records_both_expected_and_actual(tmp_path):
    result = run_python(problem(), write(tmp_path, WRONG), cases())
    first = result.cases[0]
    assert first.expected == 3
    assert first.actual == 2


def test_partial_failure_is_reported_per_case(tmp_path):
    source = """
class Solution:
    def addTwo(self, a, b):
        return 3 if a == 1 else 0
"""
    result = run_python(problem(), write(tmp_path, source), cases())
    assert [c.status for c in result.cases] == [CaseStatus.PASS, CaseStatus.FAIL]
    assert result.passed == 1


def test_exception_becomes_an_error_case_not_a_crash(tmp_path):
    result = run_python(problem(), write(tmp_path, RAISES), cases())
    assert all(c.status is CaseStatus.ERROR for c in result.cases)
    assert "boom" in result.cases[0].error


def test_infinite_loop_is_killed_and_reported(tmp_path):
    result = run_python(problem(), write(tmp_path, HANGS), cases(), timeout_s=0.5)
    assert result.cases[0].status is CaseStatus.TIMEOUT


def test_a_hanging_case_does_not_prevent_later_cases_running(tmp_path):
    source = """
class Solution:
    def addTwo(self, a, b):
        if a == 1:
            while True:
                pass
        return a + b
"""
    result = run_python(problem(), write(tmp_path, source), cases(), timeout_s=0.5)
    assert result.cases[0].status is CaseStatus.TIMEOUT
    assert result.cases[1].status is CaseStatus.PASS


def test_syntax_error_surfaces_as_compile_error(tmp_path):
    result = run_python(problem(), write(tmp_path, SYNTAX_ERROR), cases())
    assert result.compile_error is not None
    assert "SyntaxError" in result.compile_error
    assert result.cases == []


def test_missing_entry_point_surfaces_as_compile_error(tmp_path):
    result = run_python(problem(entry_point="nope"), write(tmp_path, CORRECT), cases())
    assert result.compile_error is not None
    assert "nope" in result.compile_error


def test_tree_arguments_are_decoded_before_the_call(tmp_path):
    """The solution must receive a TreeNode, not a list."""
    source = """
class Solution:
    def depth(self, root):
        if root is None:
            return 0
        return 1 + max(self.depth(root.left), self.depth(root.right))
"""
    p = problem(entry_point="depth", params=[ParamSpec("root", "tree")])
    tests = [
        TestCase(
            id="t1",
            args={"root": [3, 9, 20, None, None, 15, 7]},
            expected=3,
            source="example",
        )
    ]
    assert run_python(p, write(tmp_path, source), tests).ok


def test_tree_returns_are_encoded_before_comparison(tmp_path):
    source = """
class Solution:
    def identity(self, root):
        return root
"""
    p = problem(
        entry_point="identity",
        params=[ParamSpec("root", "tree")],
        return_kind="tree",
    )
    tests = [
        TestCase(id="t1", args={"root": [1, 2, 3]}, expected=[1, 2, 3], source="example")
    ]
    assert run_python(p, write(tmp_path, source), tests).ok


def test_empty_case_list_is_a_vacuous_pass(tmp_path):
    result = run_python(problem(), write(tmp_path, CORRECT), [])
    assert result.total == 0
    assert result.ok


def test_summary_reads_as_a_fraction(tmp_path):
    result = run_python(problem(), write(tmp_path, CORRECT), cases())
    assert result.summary.startswith("2/2")


PRINTS = """
class Solution:
    def addTwo(self, a, b):
        print("debugging my solution")
        return a + b
"""


def test_solution_that_prints_does_not_corrupt_the_protocol(tmp_path):
    """A stray print() on the solution's own stdout must not break the
    harness's result channel."""
    result = run_python(problem(), write(tmp_path, PRINTS), cases())
    assert result.ok
    assert result.passed == 2


def _payload(case: TestCase, status="pass"):
    return {
        "id": case.id,
        "status": status,
        "expected": case.expected,
        "actual": case.expected,
        "error": None,
        "duration_ms": 1,
    }


def test_batch_timeout_preserves_results_that_already_finished():
    """Forcing a real SIGALRM-proof hang (one that survives per-case SIGALRM
    but still trips the whole-batch subprocess timeout) is not reliable in a
    test environment — it needs a tight loop inside a C extension that never
    checks for pending signals. `_collect` is the unit that decides how a
    partial results file gets attributed, so it is tested directly: this is
    exactly what the results file would contain if case c1 finished and
    wrote its line before the batch-timeout kill, and case c2 never got to
    write at all."""
    c1, c2 = cases()
    payloads = [_payload(c1)]

    result = _collect(payloads, [c1, c2])

    assert result.cases[0].status is CaseStatus.PASS
    assert result.cases[1].status is CaseStatus.TIMEOUT


def test_collect_attributes_hang_to_first_missing_case_and_marks_rest_as_error():
    four_cases = [
        TestCase(id="c1", args={"a": 1, "b": 1}, expected=2, source="example"),
        TestCase(id="c2", args={"a": 2, "b": 2}, expected=4, source="example"),
        TestCase(id="c3", args={"a": 3, "b": 3}, expected=6, source="example"),
        TestCase(id="c4", args={"a": 4, "b": 4}, expected=8, source="example"),
    ]
    payloads = [_payload(four_cases[0]), _payload(four_cases[2])]

    result = _collect(payloads, four_cases)

    statuses = {c.id: c.status for c in result.cases}
    assert statuses == {
        "c1": CaseStatus.PASS,
        "c2": CaseStatus.TIMEOUT,
        "c3": CaseStatus.PASS,
        "c4": CaseStatus.ERROR,
    }


def test_a_failure_to_launch_the_harness_leaves_no_temp_file(tmp_path, monkeypatch):
    """`except subprocess.TimeoutExpired` does not cover an OSError at launch,
    so that path escaped before the results file was unlinked — leaking one
    temp file per failed rep."""
    import subprocess as subprocess_module
    import tempfile

    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    def refuse_to_launch(*args, **kwargs):
        raise OSError("Too many open files")

    monkeypatch.setattr(subprocess_module, "run", refuse_to_launch)

    cases = [TestCase(id="c1", args={"a": 1, "b": 2}, expected=3, source="example")]
    with pytest.raises(OSError):
        run_python(problem(), write(tmp_path, CORRECT), cases)

    assert list(scratch.iterdir()) == []


def test_running_a_solution_leaves_no_bytecode_beside_it(tmp_path):
    """Executing a solution must not write __pycache__ next to the source.

    The oracle runs a problem's `reference.py` in place, so bytecode would
    land inside the problem directory — which the spec intends to stay
    git-trackable and hand-editable.
    """
    solution = write(tmp_path, CORRECT)
    run_python(problem(), solution, cases())

    stray = [p.name for p in tmp_path.iterdir() if p.name != solution.name]
    assert stray == [], f"execution left artefacts beside the solution: {stray}"


# LeetCode's judge pre-imports a standard set of names, so idiomatic
# solutions — and every reference solution written against that judge — use
# `collections`, `math`, and `deque` bare. Without them the solution raises
# NameError on the first case and the reader is told their answer is wrong.
USES_LEETCODE_PRELUDE = """
class Solution:
    def addTwo(self, a, b):
        counts = collections.Counter([a, b])
        queue = deque(sorted(counts))
        heapq.heapify(list(counts))
        return int(math.floor(queue[0] + queue[-1])) if a != b else a + b
"""


def test_the_leetcode_prelude_is_available_without_importing_it(tmp_path):
    result = run_python(problem(), write(tmp_path, USES_LEETCODE_PRELUDE), cases())
    assert [c.status for c in result.cases] == [CaseStatus.PASS, CaseStatus.PASS], [
        c.error for c in result.cases
    ]


def test_a_solution_may_still_import_what_it_wants(tmp_path):
    """Injection seeds the namespace; it must not shadow an explicit import."""
    source = """
import math as math

class Solution:
    def addTwo(self, a, b):
        return int(math.fsum([a, b]))
"""
    result = run_python(problem(), write(tmp_path, source), cases())
    assert [c.status for c in result.cases] == [CaseStatus.PASS, CaseStatus.PASS]
