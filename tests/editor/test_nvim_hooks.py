"""The editor hooks, exercised by running nvim for real.

`:w` running nothing is invisible to every other kind of test: the Lua
registers, the CLI works, the workspace is correct, and the rep is still
useless because the two halves never meet. The only check that catches it is
writing the buffer in a real editor and looking at what appeared on disk.
"""

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from algorhythm.catalog import store as catalog
from algorhythm.catalog.models import Example, ParamSpec, Problem, TestCase
from algorhythm.editor.session import _LUA_MODULE, prepare_workspace

pytestmark = pytest.mark.skipif(
    shutil.which("nvim") is None or shutil.which("algorhythm") is None,
    reason="needs nvim and the algorhythm CLI on PATH",
)

REFERENCE = """\
class Solution:
    def twoSum(self, nums, target):
        seen = {}
        for index, value in enumerate(nums):
            if target - value in seen:
                return [seen[target - value], index]
            seen[value] = index
        return []
"""


def library(root: Path) -> Problem:
    problem = Problem(
        slug="two-sum",
        number=1,
        title="Two Sum",
        difficulty="Easy",
        topics=[],
        companies=[],
        url="",
        statement_md="Return the indices of the two numbers adding to target.",
        constraints=[],
        examples=[Example("nums = [2,7,11,15], target = 9", "[0,1]", None)],
        params=[ParamSpec("nums"), ParamSpec("target")],
        return_kind="raw",
        entry_point="twoSum",
        fetched_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
        stubs={"python": "class Solution:\n    def twoSum(self, nums, target):\n"},
    )
    directory = catalog.save_problem(problem, root=root)
    (directory / "reference.py").write_text(REFERENCE)
    catalog.save_tests(
        "two-sum",
        [
            TestCase(
                id="example-1",
                args={"nums": [2, 7, 11, 15], "target": 9},
                expected=[0, 1],
                source="example",
            ),
            TestCase(
                id="example-2",
                args={"nums": [3, 2, 4], "target": 6},
                expected=[1, 2],
                source="example",
            ),
        ],
        root=root,
    )
    return problem


def symlinked_root(tmp_path: Path) -> Path:
    """A workspace root reached through a symlink.

    pytest hands out an already-resolved tmp_path, so a workspace created
    directly under it cannot reproduce the bug — the real macOS temp root is
    `/var`, a symlink to `/private/var`. The link is what makes the path we
    hold differ from the one nvim reports.
    """
    real = tmp_path / "real"
    real.mkdir(exist_ok=True)
    link = tmp_path / "link"
    if not link.exists():
        link.symlink_to(real)
    return link


def run_nvim(workspace, *commands, home: Path):
    """Drive nvim headlessly through the same entry point the CLI uses."""
    argv = [
        "nvim",
        "--headless",
        "-u",
        "NONE",
        "-c",
        f"luafile {_LUA_MODULE}",
        "-c",
        f"lua require('algorhythm').setup('{workspace.dir}')",
    ]
    for command in commands:
        argv += ["-c", command]
    argv += ["-c", "qa!", str(workspace.solution_path)]

    subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "ALGORHYTHM_HOME": str(home)},
    )


def test_writing_the_buffer_runs_the_tests(tmp_path):
    """The reported bug: `:w` did nothing at all.

    The autocmd matched a path pattern, and on macOS the workspace lives
    under `/var/...` while nvim names the buffer `/private/var/...`, so it
    never fired.
    """
    home = tmp_path / "home"
    problem = library(home / "problems")

    workspace = prepare_workspace(
        problem, "python", stub="", root=symlinked_root(tmp_path)
    )
    workspace.solution_path.write_text(REFERENCE)
    assert workspace.results_path.read_text() == ""

    run_nvim(workspace, "w", "sleep 5", home=home)

    assert "2/2 passed" in workspace.results_path.read_text()


def test_the_review_command_writes_a_review(tmp_path):
    """Ollama is not required: an unreachable reviewer still writes the
    reason, which is what the pane is meant to show."""
    home = tmp_path / "home"
    problem = library(home / "problems")

    workspace = prepare_workspace(
        problem, "python", stub="", root=symlinked_root(tmp_path)
    )
    workspace.solution_path.write_text(REFERENCE)

    run_nvim(workspace, "Review", "sleep 10", home=home)

    assert workspace.review_path.read_text().strip() != ""


def test_the_statement_and_results_panes_are_not_editable(tmp_path):
    """They are generated files; a stray keystroke must not dirty them."""
    home = tmp_path / "home"
    problem = library(home / "problems")
    workspace = prepare_workspace(
        problem, "python", stub="", root=symlinked_root(tmp_path)
    )

    probe = tmp_path / "modifiable.json"
    run_nvim(
        workspace,
        "lua local out = {} "
        "for _, w in ipairs(vim.api.nvim_list_wins()) do "
        "  local b = vim.api.nvim_win_get_buf(w) "
        "  out[vim.api.nvim_buf_get_name(b)] = vim.bo[b].modifiable "
        "end "
        f"vim.fn.writefile({{vim.json.encode(out)}}, '{probe}')",
        home=home,
    )

    states = json.loads(probe.read_text())
    for name, modifiable in states.items():
        expected = name.endswith("solution.py")
        assert modifiable is expected, f"{name} modifiable={modifiable}"


def pane_widths(workspace, home: Path, probe: Path, *commands):
    """Width of every window, keyed by the file it is showing."""
    run_nvim(
        workspace,
        *commands,
        "lua local out = {} "
        "for _, w in ipairs(vim.api.nvim_list_wins()) do "
        "  local name = vim.api.nvim_buf_get_name(vim.api.nvim_win_get_buf(w)) "
        "  out[vim.fn.fnamemodify(name, ':t')] = vim.api.nvim_win_get_width(w) "
        "end "
        f"vim.fn.writefile({{vim.json.encode(out)}}, '{probe}')",
        home=home,
    )
    return json.loads(probe.read_text())


def test_the_statement_and_solution_panes_are_equal_width(tmp_path):
    """The two panes you read and write are the work; split them evenly.

    One column goes to the separator between them, so an exact halving is
    not possible on an odd width — off by one is the closest there is.
    """
    home = tmp_path / "home"
    problem = library(home / "problems")
    workspace = prepare_workspace(
        problem, "python", stub="", root=symlinked_root(tmp_path)
    )

    widths = pane_widths(workspace, home, tmp_path / "widths.json")

    statement = widths["statement.md"]
    solution = widths["solution.py"]
    assert abs(statement - solution) <= 1, widths


def test_the_panes_stay_equal_once_the_review_opens(tmp_path):
    """The review pane must not take its columns from the solution alone.

    A third pane has to come from somewhere, but taking it all from one
    side leaves the answer pane too narrow to write code in — 20 columns,
    against a 32-column statement.
    """
    home = tmp_path / "home"
    problem = library(home / "problems")
    workspace = prepare_workspace(
        problem, "python", stub="", root=symlinked_root(tmp_path)
    )
    workspace.solution_path.write_text(REFERENCE)

    widths = pane_widths(
        workspace, home, tmp_path / "widths.json", "Review", "sleep 6"
    )

    assert "review.md" in widths, widths
    assert abs(widths["statement.md"] - widths["solution.py"]) <= 1, widths
