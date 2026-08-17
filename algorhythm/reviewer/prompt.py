"""Prompt construction.

The reference solution and concrete test results are the whole reason a 7B
model can do this job. Without them the model is being asked to recall the
optimal approach for a specific problem, which is exactly what small models
are worst at. With them it is comparing two pieces of code, which is a much
easier task.
"""

from __future__ import annotations

from algorhythm.reviewer.protocol import ReviewRequest
from algorhythm.runner.harness import CaseStatus, RunResult

SYSTEM_PROMPT = """You are a technical interview coach reviewing a candidate's \
solution to a data-structures problem. You are given the problem, a known-good \
reference solution, the candidate's submission, and the results of running it \
against a local test suite.

Your job is to tell the candidate how far their solution is from the recommended \
one. Focus on the gap that matters most for interview performance: whether they \
reached for the right technique. If they used a different approach than the \
reference, say what the reference does and why it is preferred. Mention time and \
space complexity when the two solutions differ on it. Mention edge cases only when \
a test actually failed on one.

Write plain prose, a short paragraph or two. Do not use headings or bullet lists. \
Do not restate the problem. Do not praise generically.

The test results are authoritative for correctness — do not claim the code is \
wrong when the tests passed, or right when they failed.

If a "Previous attempt" section is given, it is what this same candidate wrote \
for this same problem the last time they saw it. In `since_last`, compare the \
candidate's submission against THAT previous attempt — not against the reference \
solution, which is what `review` is for. Say what they changed between their own \
two attempts and whether it is an improvement: the technique, the complexity, a \
bug that is gone or newly introduced. If the two attempts are essentially the \
same approach, say that. Never mention the reference in `since_last`. Leave \
`since_last` out entirely when no previous attempt is given.

Finish by proposing a spaced-repetition grade:
  again - could not solve it, or the approach was fundamentally wrong
  hard  - solved it, but with the wrong technique or notably worse complexity
  good  - essentially the reference approach, with minor differences
  easy  - clean, direct, and equivalent to the reference with no fumbling
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "review": {"type": "string"},
        "proposed_grade": {
            "type": "string",
            "enum": ["again", "hard", "good", "easy"],
        },
        "grade_reason": {"type": "string"},
        "since_last": {"type": "string"},
    },
    # `since_last` is deliberately optional: required would make the model
    # invent a comparison on a first rep, when there is nothing to compare.
    "required": ["review", "proposed_grade"],
}


def response_schema(request: ReviewRequest) -> dict:
    """The schema for one request.

    `since_last` is required exactly when a previous attempt is being sent.
    Optional was not enough: asked for an optional string, a model simply
    leaves it out — the comparison silently never appeared. Ollama enforces
    the schema, so requiring it is what makes the remark actually arrive,
    and requiring it only then is what stops a first rep inventing one.
    """
    schema = {
        "type": "object",
        "properties": dict(RESPONSE_SCHEMA["properties"]),
        "required": list(RESPONSE_SCHEMA["required"]),
    }
    if _previous_section(request):
        schema["required"].append("since_last")
    return schema


def _last_line(error: str | None) -> str:
    """The final meaningful line of a traceback.

    `splitlines()[-1:]` would be a list slice, rendering the literal
    `['ValueError: bad']` into the prompt instead of the message itself.
    """
    lines = [line for line in (error or "").strip().splitlines() if line.strip()]
    return lines[-1] if lines else "no detail available"


def _format_results(result: RunResult) -> str:
    if result.compile_error:
        return f"The submission did not compile or import:\n{result.compile_error}"
    if result.total == 0:
        return "No tests were run."

    lines = [f"Tests: {result.summary}"]
    for case in result.cases:
        if case.status is CaseStatus.PASS:
            continue
        detail = {
            CaseStatus.FAIL: f"expected {case.expected!r}, got {case.actual!r}",
            CaseStatus.ERROR: f"raised: {_last_line(case.error)}",
            CaseStatus.TIMEOUT: "timed out",
        }.get(case.status, case.status.value)
        lines.append(f"  - {case.id}: {case.status.value} ({detail})")
    return "\n".join(lines)


def _previous_section(request: ReviewRequest) -> str:
    """The previous attempt, when there is a meaningful one.

    Skipped when it matches what was just written. Identical text is a whole
    solution of context buying nothing, and everything in the prompt competes
    for a 7B model's attention with the reference comparison — which is the
    part that carries the review.
    """
    previous = request.previous_source
    if not previous or _same_code(previous, request.solution_source):
        return ""
    # The instruction is repeated here, next to the code, and not left to
    # the system prompt alone. Three different models returned `since_last`
    # as an empty string with it stated only up there — they put the
    # comparison in `review` and left the field blank.
    return f"""
## Previous attempt ({request.language}) — the SAME candidate, last time

```{request.language}
{previous}
```

`since_last` must be a non-empty sentence comparing the submission above
with this previous attempt: what changed, and whether it is better. Do not
leave it blank.
"""


def _same_code(left: str, right: str) -> str:
    """Compare ignoring indentation and blank lines, so a reformat does not
    read as a change worth remarking on."""
    def strip(text: str) -> list[str]:
        return [line.strip() for line in text.strip().splitlines() if line.strip()]

    return strip(left) == strip(right)


def build_prompt(request: ReviewRequest) -> str:
    problem = request.problem
    reference = (
        request.reference_source
        or "(no reference solution is available for this problem — say so in your "
        "review, and do not invent a comparison)"
    )

    constraints = "\n".join(f"- {c}" for c in problem.constraints) or "(none recorded)"

    return f"""## Problem

{problem.number}. {problem.title} ({problem.difficulty})
Topics: {', '.join(problem.topics) or 'none recorded'}

{problem.statement_md}

Constraints:
{constraints}

## Reference solution ({request.language})

```{request.language}
{reference}
```

## Candidate's submission ({request.language})

```{request.language}
{request.solution_source}
```

{_previous_section(request)}
## Test results

{_format_results(request.run_result)}
"""
