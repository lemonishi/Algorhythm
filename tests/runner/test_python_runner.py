from datetime import datetime, timezone

import pytest

from algorhythm.catalog.models import ParamSpec, Problem, TestCase
from algorhythm.runner.harness import CaseStatus
from algorhythm.runner.python_runner import run_python


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
