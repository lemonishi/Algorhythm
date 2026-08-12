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
