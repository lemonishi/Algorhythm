from datetime import datetime, timezone

from algorhythm.catalog.models import ParamSpec, Problem
from algorhythm.reviewer.prompt import SYSTEM_PROMPT, build_prompt
from algorhythm.reviewer.protocol import ReviewRequest
from algorhythm.runner.harness import CaseResult, CaseStatus, RunResult


def problem() -> Problem:
    return Problem(
        slug="two-sum",
        number=1,
        title="Two Sum",
        difficulty="Easy",
        topics=["Array", "Hash Table"],
        companies=[],
        url="https://leetcode.com/problems/two-sum/",
        statement_md="Return indices of the two numbers that add to target.",
        constraints=["2 <= nums.length <= 10^4"],
        examples=[],
        params=[ParamSpec("nums"), ParamSpec("target")],
        return_kind="raw",
        entry_point="twoSum",
        fetched_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )


def request(run_result=None) -> ReviewRequest:
    return ReviewRequest(
        problem=problem(),
        language="python",
        solution_source="class Solution:\n    def twoSum(self, nums, target): ...",
        reference_source="# reference: hash map, O(n)",
        run_result=run_result or RunResult(cases=[]),
    )


def test_prompt_includes_the_problem_title_and_statement():
    text = build_prompt(request())
    assert "Two Sum" in text
    assert "Return indices" in text


def test_prompt_includes_the_reference_solution():
    """Grounding is what makes a 7B model viable here — without the
    reference this becomes a recall task it will fail."""
    assert "hash map, O(n)" in build_prompt(request())


def test_prompt_includes_the_submitted_solution():
    assert "def twoSum" in build_prompt(request())


def test_prompt_states_the_language():
    assert "python" in build_prompt(request()).lower()


def test_prompt_reports_a_clean_test_run():
    run = RunResult(cases=[CaseResult(id="c1", status=CaseStatus.PASS)])
    assert "1/1 passed" in build_prompt(request(run))


def test_prompt_names_failing_cases_with_inputs():
    run = RunResult(
        cases=[
            CaseResult(
                id="oracle-2",
                status=CaseStatus.FAIL,
                expected=[0, 1],
                actual=[1, 0],
            )
        ]
    )
    text = build_prompt(request(run))
    assert "oracle-2" in text
    assert "[0, 1]" in text
    assert "[1, 0]" in text


def test_prompt_reports_a_compile_error():
    run = RunResult(compile_error="SyntaxError: invalid syntax")
    assert "SyntaxError" in build_prompt(request(run))


def test_prompt_flags_a_missing_reference_explicitly():
    """The review must say so rather than silently inventing a comparison."""
    req = ReviewRequest(
        problem=problem(),
        language="python",
        solution_source="x",
        reference_source=None,
        run_result=RunResult(cases=[]),
    )
    assert "no reference solution" in build_prompt(req).lower()


def test_system_prompt_asks_for_prose_not_a_rubric():
    assert "rubric" not in SYSTEM_PROMPT.lower()
    assert "again" in SYSTEM_PROMPT and "easy" in SYSTEM_PROMPT


def test_system_prompt_is_long_enough_to_be_cacheable():
    """Opus-style prompt caching needs a stable prefix of real size; more
    importantly a short prompt underspecifies the task for a 7B model."""
    assert len(SYSTEM_PROMPT) > 400
