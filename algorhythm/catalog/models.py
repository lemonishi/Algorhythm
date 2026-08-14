"""Problem content model.

`ParamSpec.kind` is the bridge between LeetCode's JSON-array notation and the
object graphs its signatures actually take. `[3,9,20,null,null,15,7]` is a
`tree`; `[[1,1,0],[0,1,0]]` is a `grid`. The runners use this to decide how
to deserialize each argument before calling the solution.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

PARAM_KINDS = frozenset({"raw", "tree", "linked_list", "grid", "graph"})
LANGUAGES = {"python": "py", "cpp": "cpp"}

# How a returned value is compared with the expected one.
#
# `exact` is the default and the honest one. `unordered` exists because
# LeetCode says "in any order" for a real class of problems — group-anagrams,
# 3sum, top-k-frequent — where a correct answer legitimately differs from the
# reference's ordering, and exact comparison would fail a right answer. It
# sorts at every level of nesting before comparing, so it must never be set
# on a problem where order is part of the answer (a level-order traversal).
COMPARISONS = frozenset({"exact", "unordered"})


@dataclass(frozen=True)
class ParamSpec:
    name: str
    kind: str = "raw"

    def __post_init__(self) -> None:
        if self.kind not in PARAM_KINDS:
            raise ValueError(f"unknown param kind: {self.kind}")


@dataclass(frozen=True)
class Example:
    input_text: str
    output_text: str
    explanation: str | None = None


@dataclass(frozen=True)
class TestCase:
    # Not a pytest test class, despite the name — this tells pytest's
    # `Test*` collection heuristic to leave it alone.
    __test__ = False

    id: str
    args: dict[str, Any]
    expected: Any
    source: str  # "example" | "oracle"


@dataclass(frozen=True)
class Problem:
    slug: str
    number: int
    title: str
    difficulty: str
    topics: list[str]
    companies: list[str]
    url: str
    statement_md: str
    constraints: list[str]
    examples: list[Example]
    params: list[ParamSpec]
    return_kind: str
    entry_point: str
    fetched_at: datetime
    company_tags_source: str | None = None
    company_tags_asof: str | None = None
    comparison: str = "exact"
    # The parameter whose mutated value IS the answer, for problems that
    # return nothing — rotate-image, set-matrix-zeroes, reorder-list. None
    # for everything else, where the answer is what the method returned.
    answer_param: str | None = None
    # LeetCode's own starter code, keyed by our language names. This is what
    # the solution buffer is seeded with, and what the C++ harness includes,
    # so an empty dict means a blank rep.
    stubs: dict[str, str] = field(default_factory=dict)
    # The worked examples as runnable cases. Empty either because the problem
    # states none, or because they could not be parsed with confidence — see
    # `fetch._example_cases`, which refuses to guess.
    example_cases: list[TestCase] = field(default_factory=list)

    @property
    def dirname(self) -> str:
        return f"{self.number:04d}-{self.slug}"

    def _replace_number(self, number: int) -> "Problem":
        """Test helper; also handy when correcting a bad fetch by hand."""
        return replace(self, number=number)
