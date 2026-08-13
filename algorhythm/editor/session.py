"""Scratch workspace preparation and nvim launch.

Each rep gets its own directory so nothing leaks between problems and an
abandoned rep leaves no trace in the database.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from algorhythm.catalog.models import LANGUAGES, Problem
from algorhythm.catalog.visualize import visualize

_LUA_MODULE = Path(__file__).parent / "lua" / "algorhythm.lua"


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


def _drawing_for(problem: Problem, input_text: str) -> str | None:
    """Draw the first structural parameter found in the example input."""
    for spec in problem.params:
        if spec.kind == "raw":
            continue
        marker = f"{spec.name} = "
        if marker not in input_text:
            continue
        fragment = input_text.split(marker, 1)[1].split(", ")[0].strip()
        try:
            value = json.loads(fragment)  # JSON `null` decodes to None
        except json.JSONDecodeError:
            return None
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


def nvim_command(workspace: Workspace) -> list[str]:
    return [
        "nvim",
        "-c",
        f"luafile {_LUA_MODULE}",
        "-c",
        f"lua require('algorhythm').setup('{workspace.dir}')",
        str(workspace.solution_path),
    ]


def launch(workspace: Workspace, *, runner=subprocess.run) -> int:
    result = runner(nvim_command(workspace))
    return getattr(result, "returncode", 0)
