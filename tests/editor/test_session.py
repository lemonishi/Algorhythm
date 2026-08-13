import json
from datetime import datetime, timezone

import pytest

from algorhythm.catalog.models import Example, ParamSpec, Problem
from algorhythm.editor.session import launch, nvim_command, prepare_workspace


def problem() -> Problem:
    return Problem(
        slug="binary-tree-level-order-traversal",
        number=102,
        title="Binary Tree Level Order Traversal",
        difficulty="Medium",
        topics=["Tree"],
        companies=["Amazon"],
        url="https://leetcode.com/problems/binary-tree-level-order-traversal/",
        statement_md="Return the level order traversal.",
        constraints=["0 <= nodes <= 2000"],
        examples=[
            Example(
                input_text="root = [3,9,20,null,null,15,7]",
                output_text="[[3],[9,20],[15,7]]",
                explanation=None,
            )
        ],
        params=[ParamSpec("root", "tree")],
        return_kind="raw",
        entry_point="levelOrder",
        fetched_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )


STUB = "class Solution:\n    def levelOrder(self, root):\n        "


def test_workspace_files_are_created(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    assert ws.statement_path.exists()
    assert ws.solution_path.exists()
    assert ws.meta_path.exists()


def test_solution_file_uses_the_language_extension(tmp_path):
    py = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    cpp = prepare_workspace(problem(), "cpp", stub="// stub", root=tmp_path)
    assert py.solution_path.name == "solution.py"
    assert cpp.solution_path.name == "solution.cpp"


def test_solution_is_seeded_with_the_stub(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    assert ws.solution_path.read_text() == STUB


def test_previous_attempt_takes_precedence_over_the_stub(tmp_path):
    previous = "class Solution:\n    def levelOrder(self, root):\n        return []"
    ws = prepare_workspace(
        problem(), "python", stub=STUB, previous_attempt=previous, root=tmp_path
    )
    assert ws.solution_path.read_text() == previous


def test_statement_includes_the_title_and_difficulty(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    text = ws.statement_path.read_text()
    assert "102. Binary Tree Level Order Traversal" in text
    assert "Medium" in text


def test_statement_includes_topics_and_companies(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    text = ws.statement_path.read_text()
    assert "Tree" in text
    assert "Amazon" in text


def test_statement_includes_examples_and_constraints(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    text = ws.statement_path.read_text()
    assert "root = [3,9,20,null,null,15,7]" in text
    assert "0 <= nodes <= 2000" in text


def test_statement_renders_tree_examples_as_ascii(tmp_path):
    """The whole point of the visualiser — a tree example should be drawn,
    not just printed as an array."""
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    text = ws.statement_path.read_text()
    assert "/" in text and "\\" in text


def test_meta_records_what_the_editor_hooks_need(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    meta = json.loads(ws.meta_path.read_text())
    assert meta["slug"] == "binary-tree-level-order-traversal"
    assert meta["language"] == "python"


def test_results_and_review_files_start_empty_but_present(tmp_path):
    """nvim opens them as splits, so they must exist before launch."""
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    assert ws.results_path.exists()
    assert ws.review_path.exists()


def test_each_workspace_is_isolated(tmp_path):
    first = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    second = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    assert first.dir != second.dir


def test_nvim_command_sources_the_lua_module(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    command = nvim_command(ws)
    assert command[0] == "nvim"
    assert any("algorhythm.lua" in part for part in command)


def test_nvim_command_opens_the_solution_file(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    assert str(ws.solution_path) in nvim_command(ws)


def test_launch_returns_the_editor_exit_code(tmp_path):
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    calls = []

    class Result:
        returncode = 0

    def fake_runner(command, **kwargs):
        calls.append(command)
        return Result()

    assert launch(ws, runner=fake_runner) == 0
    assert calls and calls[0][0] == "nvim"
