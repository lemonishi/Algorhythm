import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from algorhythm.catalog.models import Example, ParamSpec, Problem
from algorhythm.editor.session import (
    Workspace,
    _lua_string,
    launch,
    nvim_command,
    prepare_workspace,
    workspace_from_dir,
)


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
    """Always the stub — there is nothing else it can be seeded with.

    A repeat rep gets the same blank buffer as the first one: the grade is
    a statement about recall, and last time's answer sitting in the editor
    would make it meaningless.
    """
    ws = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    assert ws.solution_path.read_text() == STUB
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


def test_statement_renders_tree_examples_written_with_spaces(tmp_path):
    """LeetCode's real formatting puts a space after each comma, e.g.
    `root = [3, 9, 20, null, null, 15, 7]` — the fixture above happens not to
    have any, which is why it alone wouldn't catch a naive `", "` split."""
    p = replace(
        problem(),
        examples=[
            Example(
                input_text="root = [3, 9, 20, null, null, 15, 7]",
                output_text="[[3],[9,20],[15,7]]",
                explanation=None,
            )
        ],
    )
    ws = prepare_workspace(p, "python", stub=STUB, root=tmp_path)
    text = ws.statement_path.read_text()
    assert "/" in text and "\\" in text


def test_drawing_isolates_the_full_value_from_a_multi_param_example(tmp_path):
    """A `", "` split would truncate `nums` to just its first element once a
    trailing `target = 9` follows it."""
    p = replace(
        problem(),
        params=[ParamSpec("nums", "linked_list"), ParamSpec("target", "raw")],
        examples=[
            Example(
                input_text="nums = [2, 7, 11, 15], target = 9",
                output_text="[0,1]",
                explanation=None,
            )
        ],
    )
    ws = prepare_workspace(p, "python", stub=STUB, root=tmp_path)
    text = ws.statement_path.read_text()
    assert "2 -> 7 -> 11 -> 15 -> null" in text


def test_statement_renders_grid_examples_written_with_spaces(tmp_path):
    p = replace(
        problem(),
        params=[ParamSpec("grid", "grid")],
        examples=[
            Example(
                input_text="grid = [[1, 1], [0, 1]]",
                output_text="2",
                explanation=None,
            )
        ],
    )
    ws = prepare_workspace(p, "python", stub=STUB, root=tmp_path)
    text = ws.statement_path.read_text()
    assert "1 1" in text
    assert "0 1" in text


def test_lua_string_escapes_backslashes_and_quotes():
    assert _lua_string("plain") == "plain"
    assert _lua_string("it's") == r"it\'s"
    assert _lua_string(r"back\slash") == r"back\\slash"
    assert _lua_string(r"a'b\c") == r"a\'b\\c"


def test_workspace_from_dir_round_trips_python(tmp_path):
    original = prepare_workspace(problem(), "python", stub=STUB, root=tmp_path)
    assert workspace_from_dir(original.dir) == original


def test_workspace_from_dir_round_trips_cpp(tmp_path):
    original = prepare_workspace(problem(), "cpp", stub="// stub", root=tmp_path)
    assert workspace_from_dir(original.dir) == original


def test_workspace_from_dir_reads_slug_and_language_from_session_json(tmp_path):
    """The workspace directory name is a temp-dir artifact (`algorhythm-<slug>-XXXXXX`);
    what's authoritative is session.json. Give it a slug that the directory
    name doesn't advertise at all, so a naive re-derivation from the path
    would fail this."""
    workspace_dir = tmp_path / "some-opaque-dirname"
    workspace_dir.mkdir()
    (workspace_dir / "session.json").write_text(
        json.dumps({"slug": "totally-different-slug", "language": "cpp"})
    )

    ws = workspace_from_dir(workspace_dir)
    assert ws.slug == "totally-different-slug"
    assert ws.language == "cpp"
    assert ws.solution_path.name == "solution.cpp"


def test_nvim_command_escapes_apostrophe_in_workspace_dir():
    ws = Workspace(
        dir=Path("/tmp/algo o'reilly/dir"),
        statement_path=Path("/tmp/algo o'reilly/dir/statement.md"),
        solution_path=Path("/tmp/algo o'reilly/dir/solution.py"),
        results_path=Path("/tmp/algo o'reilly/dir/results.txt"),
        review_path=Path("/tmp/algo o'reilly/dir/review.md"),
        meta_path=Path("/tmp/algo o'reilly/dir/session.json"),
        language="python",
        slug="two-sum",
    )
    command = nvim_command(ws)
    setup_command = next(part for part in command if "require('algorhythm')" in part)
    assert setup_command == r"lua require('algorhythm').setup('/tmp/algo o\'reilly/dir')"


def test_a_cycle_is_not_drawn_as_a_list_ending_in_null(tmp_path):
    """linked-list-cycle's example is `head = [3,2,0,-4], pos = 1`.

    Drawing that as `... -> -4 -> null` states the opposite of the thing the
    problem asks about. `pos` is not a parameter of the signature, so it has
    to be picked up from the example text alongside the list itself.
    """
    p = replace(
        problem(),
        params=[ParamSpec("head", "linked_list")],
        examples=[
            Example(
                input_text="head = [3,2,0,-4], pos = 1",
                output_text="true",
                explanation=None,
            )
        ],
    )
    ws = prepare_workspace(p, "python", stub="", root=tmp_path)
    text = ws.statement_path.read_text()
    assert "-> null" not in text
    assert "points back to index 1" in text


def test_a_list_without_a_cycle_still_ends_in_null(tmp_path):
    p = replace(
        problem(),
        params=[ParamSpec("head", "linked_list")],
        examples=[
            Example(
                input_text="head = [1,2], pos = -1",
                output_text="false",
                explanation=None,
            )
        ],
    )
    ws = prepare_workspace(p, "python", stub="", root=tmp_path)
    assert "1 -> 2 -> null" in ws.statement_path.read_text()


def test_a_drawing_survives_the_statement_naming_the_argument_differently(tmp_path):
    """clone-graph's signature takes `node`; its example says `adjList`.

    With one structural parameter there is no ambiguity about what the sole
    assignment refers to, and refusing to draw it loses the only picture the
    problem has.
    """
    p = replace(
        problem(),
        params=[ParamSpec("node", "graph")],
        examples=[
            Example(
                input_text="adjList = [[2,4],[1,3],[2,4],[1,3]]",
                output_text="[[2,4],[1,3],[2,4],[1,3]]",
                explanation=None,
            )
        ],
    )
    ws = prepare_workspace(p, "python", stub="", root=tmp_path)
    text = ws.statement_path.read_text()
    assert "1 -> 2, 4" in text
    assert "4 -> 1, 3" in text


def test_the_workspace_path_is_fully_resolved(tmp_path):
    """nvim names a buffer by its real path, so ours has to be real too.

    On macOS the temp root is `/var/...`, a symlink to `/private/var/...`.
    An unresolved workspace path does not match what the editor reports for
    the buffer, and anything comparing the two silently does nothing — which
    is exactly how `:w` came to run no tests at all.
    """
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)

    ws = prepare_workspace(problem(), "python", stub="", root=link)

    assert ws.dir == ws.dir.resolve()
    assert ws.solution_path == ws.solution_path.resolve()
    assert ws.statement_path.exists()
