"""LeetCode GraphQL client.

Uses the same public endpoint LeetCode's own frontend uses. No auth needed
for public problems.

Available: statement, examples, constraints, difficulty, topic tags, and
codeSnippets (the real per-language signatures, used verbatim as our stubs).

Not available: reference solutions, the hidden judge suite, and company
tags — all Premium. Those are sourced elsewhere.

This module is the single point of contact with LeetCode's schema. When
they change it, everything that breaks breaks here.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

from algorhythm.catalog.models import Example, ParamSpec, Problem, TestCase

GRAPHQL_URL = "https://leetcode.com/graphql"

QUESTION_QUERY = """
query questionData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionFrontendId
    title
    titleSlug
    difficulty
    content
    exampleTestcases
    topicTags { name slug }
    codeSnippets { lang langSlug code }
    hints
  }
}
"""

LANG_SLUGS = {"python3": "python", "cpp": "cpp"}

# Maps a Python type annotation fragment to the deserialization kind the
# runners need. Order matters: check the most specific first.
_KIND_HINTS = (
    ("TreeNode", "tree"),
    ("ListNode", "linked_list"),
    # Before `List[List[`, because clone-graph annotates its parameter
    # `Optional['Node']` while its RETURN is written the same way — and after
    # the two node types, whose names both contain "Node".
    ("'Node'", "graph"),
    ("List[List[", "grid"),
)


class FetchError(Exception):
    pass


def _strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


# The two containers LeetCode wraps a worked example in. <pre> is the older
# form; the example-block div is the newer one, and both are served today —
# contains-duplicate uses the div while two-sum still uses <pre>. Matching
# them in one alternation keeps the examples in document order, which is
# what pairs them with `exampleTestcases`.
_EXAMPLE_BLOCK = re.compile(
    r"<pre>(?P<pre>.*?)</pre>"
    r"|<div[^>]*class=\"[^\"]*example-block[^\"]*\"[^>]*>(?P<div>.*?)</div>",
    flags=re.S,
)


def _extract_examples(content: str) -> list[Example]:
    """Worked examples, each carrying bolded Input/Output/Explanation labels.

    A miss here is silent and expensive: the problem seeds with no examples,
    which also means no example cases and no seed input for the oracle, so
    the rep opens and reports `0/0 passed` with nothing to check against.
    """
    examples: list[Example] = []
    for match in _EXAMPLE_BLOCK.finditer(content):
        block = match.group("pre") or match.group("div") or ""
        text = _strip_tags(block)
        fields: dict[str, list[str]] = {}
        current: str | None = None
        for line in text.splitlines():
            match = re.match(r"\s*(Input|Output|Explanation):\s*(.*)", line)
            if match:
                current = match.group(1).lower()
                fields[current] = [match.group(2).strip()]
            elif current:
                fields[current].append(line.strip())
        if "input" not in fields or "output" not in fields:
            continue
        explanation = " ".join(fields.get("explanation", [])).strip() or None
        examples.append(
            Example(
                input_text=" ".join(fields["input"]).strip(),
                output_text=" ".join(fields["output"]).strip(),
                explanation=explanation,
            )
        )
    return examples


def _extract_constraints(content: str) -> list[str]:
    # Attributes allowed: LeetCode emits `<strong class="...">` variants, and
    # the sibling Examples heading in our own recorded fixture already does.
    # A miss here is silent — constraints vanish from the statement and from
    # the review prompt, where spec 8.2 says they carry weight.
    match = re.search(
        r"<strong[^>]*>\s*Constraints:\s*</strong>.*?<ul>(.*?)</ul>",
        content,
        flags=re.S,
    )
    if not match:
        return []
    items = re.findall(r"<li>(.*?)</li>", match.group(1), flags=re.S)
    return [_strip_tags(item) for item in items if _strip_tags(item)]


def _example_cases(
    raw: str | None, examples: list[Example], params: list[ParamSpec]
) -> list[TestCase]:
    """Turn LeetCode's `exampleTestcases` into runnable cases.

    The field is newline-delimited raw argument values, one line per
    parameter, with the cases concatenated — so `[2,7,11,15]\\n9\\n[3,2,4]\\n6`
    is two cases of a two-parameter problem. Expected outputs are not in that
    field; they come from the stated Output of the matching example, paired
    positionally.

    Any doubt at all — a ragged line count, a value that will not parse, a
    case count that disagrees with the examples — returns nothing. A missing
    example case costs coverage; a misaligned one asserts a wrong expected
    value against a correct solution, which is far worse.
    """
    if not raw or not params or not examples:
        return []

    lines = raw.strip("\n").split("\n")
    if len(lines) % len(params) != 0:
        return []

    width = len(params)
    chunks = [lines[i : i + width] for i in range(0, len(lines), width)]
    if len(chunks) != len(examples):
        return []

    cases: list[TestCase] = []
    for index, (chunk, example) in enumerate(zip(chunks, examples), start=1):
        try:
            args = {
                spec.name: json.loads(line) for spec, line in zip(params, chunk)
            }
            expected = json.loads(example.output_text)
        except ValueError:  # JSONDecodeError, and anything else json raises
            return []
        cases.append(
            TestCase(
                id=f"example-{index}", args=args, expected=expected, source="example"
            )
        )
    return cases


def extract_stubs(question: dict[str, Any]) -> dict[str, str]:
    """Per-language starter code, keyed by our language names."""
    out: dict[str, str] = {}
    for snippet in question.get("codeSnippets") or []:
        name = LANG_SLUGS.get(snippet.get("langSlug"))
        if name:
            out[name] = snippet["code"]
    return out


_SOLUTION_CLASS = re.compile(r"^\s*class\s+Solution\b[^\n]*\n", flags=re.M)


def _solution_body(code: str) -> str:
    """The part of a stub that defines Solution, or all of it if unmarked.

    Every tree, linked-list, and graph stub opens with LeetCode's definition
    of the node type, and that definition carries its own
    `def __init__(self, ...)`. Searching the whole snippet reaches it first
    and yields an entry point of `__init__` with the node's fields as
    parameters — which the harness then cannot call at all.

    Skipping to `class Solution` handles both forms LeetCode ships: `#`
    comments for TreeNode and ListNode, and a docstring for Node. Stripping
    comment lines would only catch the first.
    """
    match = _SOLUTION_CLASS.search(code)
    return code[match.end() :] if match else code


def _parse_python_signature(code: str) -> tuple[str, list[ParamSpec]]:
    """Pull the method name and parameters out of the Python stub.

    `def levelOrder(self, root: Optional[TreeNode]) -> List[List[int]]:`
    becomes ("levelOrder", [ParamSpec("root", "tree")]).
    """
    # Design problems — LRU Cache, Min Stack, Trie — define their own class
    # and are exercised by a sequence of operations, not one call. There is
    # no entry point for the harness to invoke, and parsing anyway picks up
    # the constructor: a problem that seeds looking fine and cannot run.
    if not _SOLUTION_CLASS.search(code):
        raise FetchError(
            "no `class Solution` in the Python snippet — this looks like a "
            "design problem, which is exercised by a sequence of operations "
            "rather than a single call, and is not supported"
        )

    code = _solution_body(code)
    match = re.search(r"def\s+(\w+)\s*\(self\s*,?\s*(.*?)\)\s*->", code, flags=re.S)
    if not match:
        raise FetchError("could not parse the Python stub signature")

    entry_point = match.group(1)
    params: list[ParamSpec] = []
    depth = 0
    current = ""
    for char in match.group(2) + ",":
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        if char == "," and depth == 0:
            if current.strip():
                params.append(_param_from_fragment(current))
            current = ""
        else:
            current += char
    return entry_point, params


def _param_from_fragment(fragment: str) -> ParamSpec:
    name, _, annotation = fragment.partition(":")
    kind = "raw"
    for needle, candidate in _KIND_HINTS:
        if needle in annotation:
            kind = candidate
            break
    return ParamSpec(name=name.strip(), kind=kind)


def _answer_param(code: str, params: list[ParamSpec]) -> str | None:
    """The parameter holding the answer, for a method that returns nothing.

    LeetCode writes these as `-> None:` with "modify nums in-place instead"
    in the docstring. Comparing the return value against the expected grid
    fails every case with `actual=None`, which reads as a broken solution.
    The mutated argument is always the first one.
    """
    match = re.search(r"->\s*(.+?):", _solution_body(code))
    if not match or match.group(1).strip() != "None":
        return None
    return params[0].name if params else None


def _return_kind(code: str) -> str:
    """The deserialization kind for the RETURN value.

    `grid` is deliberately excluded, unlike `_param_from_fragment`. The two
    are asymmetric because they are consumed differently: parameter kinds
    drive both `decode()` and `visualize()`, but `return_kind` is only ever
    passed to `encode()` — and there `grid` and `raw` are the same identity
    function, because a returned nested list is already comparable JSON.
    Reporting `grid` here would add a distinction nothing acts on.
    """
    match = re.search(r"->\s*(.+?):", _solution_body(code))
    if not match:
        return "raw"
    annotation = match.group(1)
    for needle, candidate in _KIND_HINTS:
        if needle in annotation and candidate != "grid":
            return candidate
    return "raw"


def parse_question(
    payload: dict[str, Any],
    *,
    fetched_at: datetime,
    render: Callable[[str], str] | None = None,
) -> Problem:
    """Turn a GraphQL response body into a Problem.

    `render` converts the statement HTML to Markdown; when omitted the raw
    HTML is kept, which keeps this module independent of the renderer.
    """
    if payload.get("errors"):
        raise FetchError("; ".join(e.get("message", "?") for e in payload["errors"]))

    question = (payload.get("data") or {}).get("question")
    if not question:
        raise FetchError("question not found")

    content = question.get("content") or ""
    stubs = extract_stubs(question)
    if "python" not in stubs:
        raise FetchError("no Python snippet in response; cannot derive signature")

    entry_point, params = _parse_python_signature(stubs["python"])
    examples = _extract_examples(content)

    return Problem(
        slug=question["titleSlug"],
        number=int(question["questionFrontendId"]),
        title=question["title"],
        difficulty=question["difficulty"],
        topics=[t["name"] for t in question.get("topicTags") or []],
        companies=[],
        url=f"https://leetcode.com/problems/{question['titleSlug']}/",
        statement_md=render(content) if render else content,
        constraints=_extract_constraints(content),
        examples=examples,
        params=params,
        return_kind=_return_kind(stubs["python"]),
        answer_param=_answer_param(stubs["python"], params),
        entry_point=entry_point,
        fetched_at=fetched_at,
        company_tags_source=None,
        company_tags_asof=None,
        stubs=stubs,
        example_cases=_example_cases(
            question.get("exampleTestcases"), examples, params
        ),
    )


def fetch_question(slug: str, *, client=None) -> Problem:
    """Network call. Never exercised in tests — see the recorded fixtures."""
    import httpx

    from algorhythm.catalog.render import render_statement

    owns_client = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        response = client.post(
            GRAPHQL_URL,
            json={"query": QUESTION_QUERY, "variables": {"titleSlug": slug}},
            headers={
                "Content-Type": "application/json",
                "Referer": f"https://leetcode.com/problems/{slug}/",
                "User-Agent": "algorhythm/0.1 (personal study tool)",
            },
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the user
        raise FetchError(f"fetching {slug!r} failed: {exc}") from exc
    finally:
        if owns_client:
            client.close()

    return parse_question(
        payload, fetched_at=datetime.now(tz=timezone.utc), render=render_statement
    )
