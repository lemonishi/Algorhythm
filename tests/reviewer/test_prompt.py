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


def request(run_result=None, previous_source=None) -> ReviewRequest:
    return ReviewRequest(
        problem=problem(),
        language="python",
        solution_source="class Solution:\n    def twoSum(self, nums, target): ...",
        reference_source="# reference: hash map, O(n)",
        run_result=run_result or RunResult(cases=[]),
        previous_source=previous_source,
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
