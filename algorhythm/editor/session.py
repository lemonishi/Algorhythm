"""Scratch workspace preparation and nvim launch.

Each rep gets its own directory so nothing leaks between problems and an
abandoned rep leaves no trace in the database.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from algorhythm.catalog.models import LANGUAGES, Problem
from algorhythm.catalog.visualize import visualize

_LUA_MODULE = Path(__file__).parent / "lua" / "algorhythm.lua"


def _lua_string(value: str) -> str:
    """Escape a value for embedding in a single-quoted Lua literal.

    A workspace path is derived from the problem slug and a temp directory,
    but the temp root is configurable and a home directory can legitimately
    contain an apostrophe (`/Users/O'Brien/...`), which would otherwise
    terminate the literal and produce a syntax error at startup.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


@dataclass(frozen=True)
class Workspace:
    dir: Path
    statement_path: Path
    solution_path: Path
    results_path: Path
    review_path: Path
    meta_path: Path
    language: str
    slug: str


def _render_statement(problem: Problem) -> str:
    lines = [
        f"# {problem.number}. {problem.title}",
        "",
        f"**{problem.difficulty}** · {' · '.join(problem.topics) or 'untagged'}",
    ]
    if problem.companies:
        lines.append(f"Asked at: {', '.join(problem.companies)}")
    lines += ["", problem.statement_md, ""]

    for index, example in enumerate(problem.examples, start=1):
        lines.append(f"## Example {index}")
        drawing = _drawing_for(problem, example.input_text)
        if drawing:
            lines += ["", "```", drawing, "```"]
        lines += [
            "",
            f"Input:  {example.input_text}",
            f"Output: {example.output_text}",
        ]
        if example.explanation:
            lines.append(f"Explain: {example.explanation}")
        lines.append("")

    if problem.constraints:
        lines.append("## Constraints")
        lines += [f"- {c}" for c in problem.constraints]
        lines.append("")

    lines.append(f"<{problem.url}>")
    return "\n".join(lines)


def _assigned(input_text: str, name: str):
    """The value of `name = ...` in an example's input line, or None.

    raw_decode consumes exactly one JSON value and reports where it ended,
    so a trailing `, target = 9` is ignored and an array containing `, `
    (LeetCode writes `[1, 2, 3]`) stays intact. Splitting on ", " would
    truncate the value to `[1`.
    """
    marker = f"{name} = "
    if marker not in input_text:
        return None
    fragment = input_text.split(marker, 1)[1].lstrip()
    try:
        value, _ = json.JSONDecoder().raw_decode(fragment)
    except json.JSONDecodeError:
        return None
    return value


def _sole_assigned(input_text: str):
    """The value of the only assignment in the line, if there is exactly one.

    LeetCode's prose does not always use the signature's parameter name —
    clone-graph takes `node` and the example says `adjList`. With a single
    structural parameter there is nothing else the assignment could mean.
    """
    names = re.findall(r"(\w+) = ", input_text)
    return _assigned(input_text, names[0]) if len(names) == 1 else None


def _drawing_for(problem: Problem, input_text: str) -> str | None:
    """Draw the first structural parameter found in the example input."""
    for spec in problem.params:
        if spec.kind == "raw":
            continue

        value = _assigned(input_text, spec.name)
        if value is None and len(problem.params) == 1:
            value = _sole_assigned(input_text)
        if value is None:
            continue

        # `pos` names the node the tail links back to and is not a parameter
        # of the signature, so it has to be read off the example alongside
        # the list. Without it a cycle draws as `-> null`, which states the
        # opposite of what the problem is asking about.
        if spec.kind == "linked_list":
            position = _assigned(input_text, "pos")
            if isinstance(position, int) and not isinstance(position, bool):
                value = {"values": value, "pos": position}

        return visualize(value, spec.kind)
    return None


def prepare_workspace(
    problem: Problem,
    language: str,
    *,
    stub: str,
    previous_attempt: str | None = None,
    root: Path | None = None,
) -> Workspace:
    base = Path(tempfile.mkdtemp(prefix=f"algorhythm-{problem.slug}-", dir=root))
    extension = LANGUAGES[language]

    statement_path = base / "statement.md"
    solution_path = base / f"solution.{extension}"
    results_path = base / "results.txt"
    review_path = base / "review.md"
    meta_path = base / "session.json"

    statement_path.write_text(_render_statement(problem))
    solution_path.write_text(previous_attempt if previous_attempt else stub)
    results_path.write_text("")
    review_path.write_text("")
    meta_path.write_text(
        json.dumps(
            {
                "slug": problem.slug,
                "language": language,
                "entry_point": problem.entry_point,
                "started_at": datetime.now(tz=timezone.utc).isoformat(),
            },
            indent=2,
        )
    )

    return Workspace(
        dir=base,
        statement_path=statement_path,
        solution_path=solution_path,
        results_path=results_path,
        review_path=review_path,
        meta_path=meta_path,
        language=language,
        slug=problem.slug,
    )


def workspace_from_dir(workspace_dir: Path) -> Workspace:
    """Rebuild a Workspace from a directory `prepare_workspace` created.

    The editor invokes `algorhythm internal-test <dir>` with only a path, so
    something has to reconstitute the rest. Doing it here keeps the file
    layout described in exactly one place — hand-rebuilding it in the CLI
    means renaming a file in this module fails at runtime over there, with a
    FileNotFoundError rather than anything that points at the cause.
    """
    meta = json.loads((workspace_dir / "session.json").read_text())
    language = meta["language"]
    return Workspace(
        dir=workspace_dir,
        statement_path=workspace_dir / "statement.md",
        solution_path=workspace_dir / f"solution.{LANGUAGES[language]}",
        results_path=workspace_dir / "results.txt",
        review_path=workspace_dir / "review.md",
        meta_path=workspace_dir / "session.json",
        language=language,
        slug=meta["slug"],
    )


def nvim_command(workspace: Workspace) -> list[str]:
    return [
        "nvim",
        "-c",
        f"luafile {_LUA_MODULE}",
        "-c",
        f"lua require('algorhythm').setup('{_lua_string(str(workspace.dir))}')",
        str(workspace.solution_path),
    ]


def launch(workspace: Workspace, *, runner=subprocess.run) -> int:
    result = runner(nvim_command(workspace))
    return getattr(result, "returncode", 0)
