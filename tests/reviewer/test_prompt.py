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


def test_prompt_renders_an_errored_case_s_exception_message():
    """A list slice (`splitlines()[-1:]`) would render the literal
    `['ValueError: bad']` into the prompt instead of the message itself."""
    run = RunResult(
        cases=[
            CaseResult(
                id="c1",
                status=CaseStatus.ERROR,
                error="Traceback (most recent call last):\n  ...\nValueError: boom\n",
            )
        ]
    )
    text = build_prompt(request(run))
    assert "raised: ValueError: boom" in text
    assert "raised: [" not in text


def test_prompt_renders_a_fallback_for_an_errored_case_with_no_message():
    run = RunResult(cases=[CaseResult(id="c1", status=CaseStatus.ERROR, error=None)])
    text = build_prompt(request(run))
    assert "raised: []" not in text
    assert "raised: no detail available" in text


def test_prompt_reports_a_timed_out_case():
    run = RunResult(cases=[CaseResult(id="c1", status=CaseStatus.TIMEOUT)])
    assert "timed out" in build_prompt(request(run))


# -- the previous attempt ---------------------------------------------------


def test_a_previous_attempt_is_given_its_own_section():
    from algorhythm.reviewer.prompt import build_prompt

    prompt = build_prompt(request(previous_source="def old(): pass"))
    assert "Previous attempt" in prompt
    assert "def old(): pass" in prompt


def test_no_previous_attempt_adds_no_section():
    """A first rep must not carry an empty heading the model will fill in."""
    from algorhythm.reviewer.prompt import build_prompt

    assert "Previous attempt" not in build_prompt(request())


def test_an_unchanged_solution_is_not_sent_as_a_previous_attempt():
    """Identical text is a whole solution of context buying nothing.

    A 7B model is doing the work here, and everything in the prompt
    competes for its attention with the reference comparison, which is the
    part that matters.
    """
    from algorhythm.reviewer.prompt import build_prompt

    same = request().solution_source
    assert "Previous attempt" not in build_prompt(request(previous_source=same))


def test_whitespace_only_changes_do_not_count_as_a_previous_attempt():
    from algorhythm.reviewer.prompt import build_prompt

    padded = "  " + request().solution_source.replace("\n", "\n  ") + "\n\n"
    assert "Previous attempt" not in build_prompt(request(previous_source=padded))


def test_the_model_is_told_what_to_do_with_a_previous_attempt():
    from algorhythm.reviewer.prompt import SYSTEM_PROMPT

    assert "previous attempt" in SYSTEM_PROMPT.lower()


def test_the_schema_allows_but_does_not_require_a_since_last_note():
    """Required would force the model to invent one on a first rep."""
    from algorhythm.reviewer.prompt import RESPONSE_SCHEMA

    assert "since_last" in RESPONSE_SCHEMA["properties"]
    assert "since_last" not in RESPONSE_SCHEMA["required"]


def test_since_last_is_required_only_when_a_previous_attempt_is_sent():
    """Optional was not enough — the model just left it out.

    Requiring it whenever there is nothing to compare would be worse: the
    model would invent a comparison on a first rep.
    """
    from algorhythm.reviewer.prompt import response_schema

    with_previous = response_schema(request(previous_source="def old(): pass"))
    without = response_schema(request())

    assert "since_last" in with_previous["required"]
    assert "since_last" not in without["required"]


def test_an_unchanged_solution_does_not_force_a_since_last_note():
    from algorhythm.reviewer.prompt import response_schema

    same = request().solution_source
    schema = response_schema(request(previous_source=same))
    assert "since_last" not in schema["required"]


def test_building_a_schema_does_not_mutate_the_shared_one():
    from algorhythm.reviewer.prompt import RESPONSE_SCHEMA, response_schema

    response_schema(request(previous_source="def old(): pass"))
    assert "since_last" not in RESPONSE_SCHEMA["required"]


def test_the_previous_section_carries_its_own_instruction():
    """The system prompt alone was not enough.

    Three different models returned `since_last` as an empty string with
    the instruction only in the system prompt — they said the comparison in
    `review` instead and left the field blank. An imperative next to the
    code itself is what actually fills it.
    """
    from algorhythm.reviewer.prompt import build_prompt

    prompt = build_prompt(request(previous_source="def old(): pass"))
    tail = prompt[prompt.index("Previous attempt"):]
    assert "since_last" in tail
    assert "blank" in tail or "non-empty" in tail


def test_no_such_instruction_without_a_previous_attempt():
    from algorhythm.reviewer.prompt import build_prompt

    assert "since_last" not in build_prompt(request())
