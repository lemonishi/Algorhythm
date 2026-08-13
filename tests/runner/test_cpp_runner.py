import shutil
from datetime import datetime, timezone

import pytest

from algorhythm.catalog.models import ParamSpec, Problem, TestCase
from algorhythm.runner.cpp_runner import CodegenError, canonical, run_cpp
from algorhythm.runner.harness import CaseStatus

pytestmark = pytest.mark.skipif(
    shutil.which("clang++") is None, reason="clang++ not available"
)


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


def write(tmp_path, source):
    path = tmp_path / "solution.cpp"
    path.write_text(source)
    return path


CORRECT = """
class Solution {
public:
    int addTwo(int a, int b) { return a + b; }
};
"""

WRONG = """
class Solution {
public:
    int addTwo(int a, int b) { return a * b; }
};
"""

WONT_COMPILE = """
class Solution {
public:
    int addTwo(int a, int b) { return a +; }
};
"""

HANGS = """
class Solution {
public:
    int addTwo(int a, int b) { while (true) {} return 0; }
};
"""


def cases():
    return [
        TestCase(id="c1", args={"a": 1, "b": 2}, expected=3, source="example"),
        TestCase(id="c2", args={"a": 10, "b": 5}, expected=15, source="oracle"),
    ]


# -- canonical form --------------------------------------------------------

def test_canonical_ints():
    assert canonical(5) == "5"
    assert canonical(-3) == "-3"


def test_canonical_bools_are_lowercase():
    assert canonical(True) == "true"
    assert canonical(False) == "false"


def test_canonical_strings_are_quoted():
    assert canonical("ab") == '"ab"'


def test_canonical_lists_have_no_spaces():
    assert canonical([1, 2, 3]) == "[1,2,3]"


def test_canonical_nested_lists():
    assert canonical([[1, 2], [3]]) == "[[1,2],[3]]"


def test_canonical_nulls_in_tree_arrays():
    assert canonical([1, None, 2]) == "[1,null,2]"


def test_canonical_floats_use_fixed_precision():
    assert canonical(1.5) == "1.50000"


# -- execution -------------------------------------------------------------

def test_correct_solution_passes(tmp_path):
    result = run_cpp(problem(), write(tmp_path, CORRECT), cases(), cache_root=tmp_path)
    assert result.ok
    assert result.passed == 2


def test_wrong_solution_fails_with_actual_recorded(tmp_path):
    result = run_cpp(problem(), write(tmp_path, WRONG), cases(), cache_root=tmp_path)
    assert not result.ok
    assert result.cases[0].actual == "2"
    assert result.cases[0].expected == "3"


def test_compile_error_is_surfaced_not_raised(tmp_path):
    result = run_cpp(
        problem(), write(tmp_path, WONT_COMPILE), cases(), cache_root=tmp_path
    )
    assert result.compile_error is not None
    assert result.cases == []


def test_infinite_loop_marks_the_hanging_case(tmp_path):
    result = run_cpp(
        problem(), write(tmp_path, HANGS), cases(), timeout_s=1.0, cache_root=tmp_path
    )
    assert result.cases[0].status is CaseStatus.TIMEOUT


def test_second_run_reuses_the_cached_binary(tmp_path):
    """The whole point of the cache: no compiler invocation the second time."""
    path = write(tmp_path, CORRECT)
    run_cpp(problem(), path, cases(), cache_root=tmp_path)
    binaries = list((tmp_path / "cpp").glob("*"))
    mtimes = {b: b.stat().st_mtime_ns for b in binaries}
    run_cpp(problem(), path, cases(), cache_root=tmp_path)
    assert {b: b.stat().st_mtime_ns for b in binaries} == mtimes


def test_editing_the_solution_invalidates_the_cache(tmp_path):
    path = write(tmp_path, CORRECT)
    run_cpp(problem(), path, cases(), cache_root=tmp_path)
    before = set((tmp_path / "cpp").glob("*"))
    path.write_text(WRONG)
    run_cpp(problem(), path, cases(), cache_root=tmp_path)
    assert set((tmp_path / "cpp").glob("*")) != before


def test_vector_arguments_and_returns(tmp_path):
    source = """
class Solution {
public:
    vector<int> doubleAll(vector<int>& nums) {
        vector<int> out;
        for (int n : nums) out.push_back(n * 2);
        return out;
    }
};
"""
    p = problem(entry_point="doubleAll", params=[ParamSpec("nums")])
    tests = [
        TestCase(id="v1", args={"nums": [1, 2, 3]}, expected=[2, 4, 6], source="example")
    ]
    assert run_cpp(p, write(tmp_path, source), tests, cache_root=tmp_path).ok


def test_tree_arguments_are_built_before_the_call(tmp_path):
    source = """
class Solution {
public:
    int depth(TreeNode* root) {
        if (!root) return 0;
        return 1 + max(depth(root->left), depth(root->right));
    }
};
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
    assert run_cpp(p, write(tmp_path, source), tests, cache_root=tmp_path).ok


def test_string_arguments(tmp_path):
    source = """
class Solution {
public:
    int length(string s) { return (int)s.size(); }
};
"""
    p = problem(entry_point="length", params=[ParamSpec("s")])
    tests = [TestCase(id="s1", args={"s": "hello"}, expected=5, source="example")]
    assert run_cpp(p, write(tmp_path, source), tests, cache_root=tmp_path).ok


def test_unsupported_argument_type_raises_codegen_error(tmp_path):
    p = problem(entry_point="f", params=[ParamSpec("x")])
    tests = [TestCase(id="x", args={"x": {"a": 1}}, expected=1, source="example")]
    with pytest.raises(CodegenError, match="cannot express"):
        run_cpp(p, write(tmp_path, CORRECT), tests, cache_root=tmp_path)
