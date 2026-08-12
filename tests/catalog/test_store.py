from datetime import datetime, timezone

import pytest

from algorhythm.catalog.models import Example, ParamSpec, Problem, TestCase
from algorhythm.catalog.store import (
    list_slugs,
    load_problem,
    load_tests,
    reference_path,
    save_problem,
    save_tests,
    stub_path,
)

FETCHED = datetime(2026, 8, 12, tzinfo=timezone.utc)


def make_problem(slug: str = "binary-tree-level-order-traversal") -> Problem:
    return Problem(
        slug=slug,
        number=102,
        title="Binary Tree Level Order Traversal",
        difficulty="Medium",
        topics=["Tree", "Breadth-First Search"],
        companies=["Amazon", "Meta"],
        url=f"https://leetcode.com/problems/{slug}/",
        statement_md="Given the root of a binary tree, return the level order traversal.",
        constraints=["The number of nodes is in the range [0, 2000]."],
        examples=[
            Example(
                input_text="root = [3,9,20,null,null,15,7]",
                output_text="[[3],[9,20],[15,7]]",
                explanation=None,
            )
        ],
        params=[ParamSpec(name="root", kind="tree")],
        return_kind="raw",
        entry_point="levelOrder",
        fetched_at=FETCHED,
        company_tags_source="community-mirror",
        company_tags_asof="2025-03-01",
    )


def test_save_creates_the_expected_files(tmp_path):
    save_problem(make_problem(), root=tmp_path)
    d = tmp_path / "0102-binary-tree-level-order-traversal"
    assert (d / "meta.json").exists()
    assert (d / "statement.md").exists()
    assert (d / "examples.json").exists()


def test_statement_is_written_as_plain_markdown(tmp_path):
    save_problem(make_problem(), root=tmp_path)
    text = (
        tmp_path / "0102-binary-tree-level-order-traversal" / "statement.md"
    ).read_text()
    assert "Given the root of a binary tree" in text


def test_roundtrip_preserves_every_field(tmp_path):
    original = make_problem()
    save_problem(original, root=tmp_path)
    assert load_problem(original.slug, root=tmp_path) == original


def test_roundtrip_preserves_param_kinds(tmp_path):
    original = make_problem()
    save_problem(original, root=tmp_path)
    loaded = load_problem(original.slug, root=tmp_path)
    assert loaded.params == [ParamSpec(name="root", kind="tree")]


def test_load_missing_problem_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_problem("does-not-exist", root=tmp_path)


def test_list_slugs_is_sorted_by_problem_number(tmp_path):
    save_problem(make_problem("two-sum")._replace_number(1), root=tmp_path)
    save_problem(make_problem(), root=tmp_path)
    save_problem(make_problem("lru-cache")._replace_number(146), root=tmp_path)
    assert list_slugs(root=tmp_path) == [
        "two-sum",
        "binary-tree-level-order-traversal",
        "lru-cache",
    ]


def test_list_slugs_ignores_stray_files(tmp_path):
    save_problem(make_problem(), root=tmp_path)
    (tmp_path / "README.md").write_text("not a problem")
    assert list_slugs(root=tmp_path) == ["binary-tree-level-order-traversal"]


def test_tests_roundtrip(tmp_path):
    save_problem(make_problem(), root=tmp_path)
    cases = [
        TestCase(
            id="example-1",
            args={"root": [3, 9, 20, None, None, 15, 7]},
            expected=[[3], [9, 20], [15, 7]],
            source="example",
        ),
        TestCase(id="edge-empty", args={"root": []}, expected=[], source="oracle"),
    ]
    save_tests("binary-tree-level-order-traversal", cases, root=tmp_path)
    assert load_tests("binary-tree-level-order-traversal", root=tmp_path) == cases


def test_load_tests_is_empty_when_none_written(tmp_path):
    save_problem(make_problem(), root=tmp_path)
    assert load_tests("binary-tree-level-order-traversal", root=tmp_path) == []


def test_reference_and_stub_paths_use_the_right_extensions(tmp_path):
    save_problem(make_problem(), root=tmp_path)
    slug = "binary-tree-level-order-traversal"
    assert reference_path(slug, "python", root=tmp_path).name == "reference.py"
    assert reference_path(slug, "cpp", root=tmp_path).name == "reference.cpp"
    assert stub_path(slug, "python", root=tmp_path).name == "stub.py"
    assert stub_path(slug, "cpp", root=tmp_path).name == "stub.cpp"


def test_unknown_language_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown language"):
        reference_path("any", "rust", root=tmp_path)


def test_slug_lookup_does_not_match_by_suffix(tmp_path):
    """`path-sum` (#112) and `binary-tree-maximum-path-sum` (#124) are both
    real LeetCode slugs. A glob for `*-{slug}` would wrongly match the
    longer directory when looking up the shorter slug."""
    save_problem(
        make_problem("binary-tree-maximum-path-sum")._replace_number(124),
        root=tmp_path,
    )
    with pytest.raises(FileNotFoundError):
        load_problem("path-sum", root=tmp_path)


def test_list_slugs_orders_by_number_past_four_digits(tmp_path):
    save_problem(make_problem("problem-ten-thousand")._replace_number(10000), root=tmp_path)
    save_problem(make_problem("problem-nine-nine-nine-nine")._replace_number(9999), root=tmp_path)
    assert list_slugs(root=tmp_path) == [
        "problem-nine-nine-nine-nine",
        "problem-ten-thousand",
    ]
