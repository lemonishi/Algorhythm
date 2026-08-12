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
import re
from datetime import datetime, timezone
from typing import Any, Callable

from algorhythm.catalog.models import Example, ParamSpec, Problem

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
    ("List[List[", "grid"),
)


class FetchError(Exception):
    pass


def _strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _extract_examples(content: str) -> list[Example]:
    """LeetCode wraps each worked example in a <pre> block with bolded
    Input/Output/Explanation labels."""
    examples: list[Example] = []
    for block in re.findall(r"<pre>(.*?)</pre>", content, flags=re.S):
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
    match = re.search(
        r"<strong>Constraints:</strong>.*?<ul>(.*?)</ul>", content, flags=re.S
    )
    if not match:
        return []
    items = re.findall(r"<li>(.*?)</li>", match.group(1), flags=re.S)
    return [_strip_tags(item) for item in items if _strip_tags(item)]


def extract_stubs(question: dict[str, Any]) -> dict[str, str]:
    """Per-language starter code, keyed by our language names."""
    out: dict[str, str] = {}
    for snippet in question.get("codeSnippets") or []:
        name = LANG_SLUGS.get(snippet.get("langSlug"))
        if name:
            out[name] = snippet["code"]
    return out


def _parse_python_signature(code: str) -> tuple[str, list[ParamSpec]]:
    """Pull the method name and parameters out of the Python stub.

    `def levelOrder(self, root: Optional[TreeNode]) -> List[List[int]]:`
    becomes ("levelOrder", [ParamSpec("root", "tree")]).
    """
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


def _return_kind(code: str) -> str:
    match = re.search(r"->\s*(.+?):", code)
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
        examples=_extract_examples(content),
        params=params,
        return_kind=_return_kind(stubs["python"]),
        entry_point=entry_point,
        fetched_at=fetched_at,
        company_tags_source=None,
        company_tags_asof=None,
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
