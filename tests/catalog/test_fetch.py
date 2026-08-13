import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from algorhythm.catalog.fetch import FetchError, parse_question

FIXTURES = Path(__file__).parent / "fixtures"
FETCHED = datetime(2026, 8, 12, tzinfo=timezone.utc)


@pytest.fixture
def payload():
    return json.loads((FIXTURES / "level_order.json").read_text())


@pytest.fixture
def two_sum():
    """A two-parameter problem: `exampleTestcases` carries two lines per case,
    so this is what exercises the chunking."""
    return json.loads((FIXTURES / "two_sum.json").read_text())


def test_parses_identity_fields(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    assert p.slug == "binary-tree-level-order-traversal"
    assert p.number == 102
    assert p.title == "Binary Tree Level Order Traversal"
    assert p.difficulty == "Medium"


def test_parses_topic_tags(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    assert p.topics == ["Tree", "Breadth-First Search"]


def test_companies_are_empty_because_they_are_premium_only(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    assert p.companies == []
    assert p.company_tags_source is None


def test_builds_the_canonical_url(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    assert p.url == "https://leetcode.com/problems/binary-tree-level-order-traversal/"


def test_extracts_both_examples(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    assert len(p.examples) == 2
    assert p.examples[0].input_text == "root = [3,9,20,null,null,15,7]"
    assert p.examples[0].output_text == "[[3],[9,20],[15,7]]"
    assert p.examples[1].input_text == "root = [1]"


def test_extracts_constraints_as_plain_text(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    assert p.constraints == [
        "The number of nodes in the tree is in the range [0, 2000].",
        "-1000 <= Node.val <= 1000",
    ]


def test_derives_entry_point_from_the_python_snippet(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    assert p.entry_point == "levelOrder"


def test_derives_param_names_and_infers_tree_kind(payload):
    """`root: Optional[TreeNode]` must become kind='tree' or the runner will
    hand the solution a raw list and every test will fail confusingly."""
    p = parse_question(payload, fetched_at=FETCHED)
    assert [(x.name, x.kind) for x in p.params] == [("root", "tree")]


def test_render_hook_is_applied_to_the_statement(payload):
    p = parse_question(payload, fetched_at=FETCHED, render=lambda html: "RENDERED")
    assert p.statement_md == "RENDERED"


def test_statement_defaults_to_raw_content_without_a_render_hook(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    assert "<p>" in p.statement_md


def test_missing_question_raises_fetch_error():
    with pytest.raises(FetchError, match="not found"):
        parse_question({"data": {"question": None}}, fetched_at=FETCHED)


def test_graphql_errors_raise_fetch_error():
    payload = {"errors": [{"message": "boom"}]}
    with pytest.raises(FetchError, match="boom"):
        parse_question(payload, fetched_at=FETCHED)


def test_stub_extraction_returns_both_languages(payload):
    from algorhythm.catalog.fetch import extract_stubs

    stubs = extract_stubs(payload["data"]["question"])
    assert set(stubs) == {"python", "cpp"}
    assert "def levelOrder" in stubs["python"]
    assert "vector<vector<int>> levelOrder" in stubs["cpp"]


def test_problem_carries_the_stubs_for_both_languages(payload):
    """The stub is what the user's buffer is seeded with. If the Problem
    drops it, every rep opens empty — no signature on screen for Python and
    nothing for the C++ harness to #include."""
    p = parse_question(payload, fetched_at=FETCHED)
    assert set(p.stubs) == {"python", "cpp"}
    assert "def levelOrder" in p.stubs["python"]
    assert "vector<vector<int>> levelOrder" in p.stubs["cpp"]


def test_grid_shaped_returns_are_raw_because_encode_treats_them_identically(payload):
    """`levelOrder` returns `List[List[int]]`. `_return_kind` deliberately
    excludes `grid` as a candidate: return_kind only ever feeds `encode()`,
    and there `grid` and `raw` are the same identity function, so reporting
    `grid` here would add a distinction nothing acts on. Pinned here so a
    future change to this is deliberate rather than accidental."""
    p = parse_question(payload, fetched_at=FETCHED)
    assert p.return_kind == "raw"


def test_return_kind_infers_tree_and_linked_list():
    from algorhythm.catalog.fetch import _return_kind

    assert _return_kind("def f(self) -> Optional[TreeNode]:") == "tree"
    assert _return_kind("def f(self) -> ListNode:") == "linked_list"


def test_return_kind_defaults_to_raw_without_an_annotation():
    from algorhythm.catalog.fetch import _return_kind

    assert _return_kind("def f(self):") == "raw"


# -- example test cases -----------------------------------------------------
#
# Spec 7.1: the suite is example cases PLUS oracle-derived edge cases. The
# oracle explicitly excludes the seed value, so without these the example the
# user is reading is not among the cases they are tested against — and a
# problem with no runnable Python reference gets no cases at all, reporting
# `0/0 passed` with RunResult.ok True.


def test_example_cases_are_built_from_the_example_testcases(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    assert [c.id for c in p.example_cases] == ["example-1", "example-2"]
    assert all(c.source == "example" for c in p.example_cases)


def test_example_case_pairs_the_raw_input_with_the_stated_output(payload):
    p = parse_question(payload, fetched_at=FETCHED)
    first = p.example_cases[0]
    assert first.args == {"root": [3, 9, 20, None, None, 15, 7]}
    assert first.expected == [[3], [9, 20], [15, 7]]


def test_example_lines_are_chunked_by_the_parameter_count(two_sum):
    """`exampleTestcases` is one line per parameter, cases concatenated."""
    p = parse_question(two_sum, fetched_at=FETCHED)
    assert [c.args for c in p.example_cases] == [
        {"nums": [2, 7, 11, 15], "target": 9},
        {"nums": [3, 2, 4], "target": 6},
        {"nums": [3, 3], "target": 6},
    ]
    assert [c.expected for c in p.example_cases] == [[0, 1], [1, 2], [0, 1]]


def test_a_ragged_line_count_skips_example_cases_entirely(two_sum):
    """Better no example cases than cases whose arguments are shifted by one
    line — those would produce confidently wrong expectations."""
    two_sum["data"]["question"]["exampleTestcases"] = "[2,7,11,15]\n9\n[3,2,4]"
    p = parse_question(two_sum, fetched_at=FETCHED)
    assert p.example_cases == []


def test_an_unparseable_value_skips_example_cases_entirely(payload):
    payload["data"]["question"]["exampleTestcases"] = "not json\n[1]"
    p = parse_question(payload, fetched_at=FETCHED)
    assert p.example_cases == []


def test_an_unparseable_expected_output_skips_example_cases_entirely(payload):
    payload["data"]["question"]["content"] = payload["data"]["question"][
        "content"
    ].replace("[[3],[9,20],[15,7]]", "the levels, top to bottom")
    p = parse_question(payload, fetched_at=FETCHED)
    assert p.example_cases == []


def test_a_case_count_that_disagrees_with_the_examples_is_skipped(payload):
    """Pairing is positional, so a mismatched count means we cannot know
    which stated output belongs to which input."""
    payload["data"]["question"]["exampleTestcases"] = "[3,9,20,null,null,15,7]"
    p = parse_question(payload, fetched_at=FETCHED)
    assert p.example_cases == []


def test_a_missing_example_testcases_field_is_not_fatal(payload):
    del payload["data"]["question"]["exampleTestcases"]
    p = parse_question(payload, fetched_at=FETCHED)
    assert p.example_cases == []
    assert p.entry_point == "levelOrder"
