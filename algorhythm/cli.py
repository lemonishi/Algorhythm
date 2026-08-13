"""Typer entry point.

`internal-test` and `internal-review` are called by the nvim Lua module,
not by humans; they read a workspace directory and write their output to a
file the editor then reloads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import typer

from algorhythm import config
from algorhythm.catalog import store as catalog
from algorhythm.runner.cpp_runner import run_cpp
from algorhythm.runner.python_runner import run_python
from algorhythm.scheduler.queue import QueueConfig, build_queue
from algorhythm.store.db import connect
from algorhythm.store.repository import Repository

app = typer.Typer(add_completion=False, help="Spaced repetition for DSA interviews.")


def _repo() -> Repository:
    return Repository(connect(config.db_path()))


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _read(path: Path) -> str | None:
    return path.read_text() if path.exists() else None


def _execute(problem, workspace, cases):
    runner = run_python if workspace.language == "python" else run_cpp
    return runner(problem, workspace.solution_path, cases)


@app.command("list")
def list_problems() -> None:
    """Show the library and each problem's next due date."""
    repo = _repo()
    for slug in catalog.list_slugs():
        row = repo.get_schedule(slug)
        when = row.due_at.date().isoformat() if row else "unseen"
        reps = row.state.reps if row else 0
        typer.echo(f"{when:>10}  reps={reps:<3} {slug}")


@app.command()
def stats() -> None:
    """Counts of scheduled problems, reviews, and attempts."""
    for key, value in _repo().counts().items():
        typer.echo(f"{key:>10}: {value}")


@app.command()
def add(slug: str) -> None:
    """Fetch a problem from LeetCode and add it to the library."""
    from algorhythm.catalog.fetch import FetchError, extract_stubs, fetch_question

    try:
        problem = fetch_question(slug)
    except FetchError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    directory = catalog.save_problem(problem)
    typer.echo(f"added {problem.number}. {problem.title} -> {directory}")


@app.command("internal-test", hidden=True)
def internal_test(workspace_dir: Path) -> None:
    """Run the tests for a workspace and write results.txt. Called by nvim."""
    from algorhythm.editor.session import workspace_from_dir

    workspace = workspace_from_dir(workspace_dir)
    problem = catalog.load_problem(workspace.slug)
    cases = catalog.load_tests(workspace.slug)

    result = _execute(problem, workspace, cases)

    lines = [result.summary, ""]
    if result.compile_error:
        lines.append(result.compile_error)
    for case in result.cases:
        marker = "ok  " if case.status.value == "pass" else "FAIL"
        lines.append(f"{marker} {case.id}  {case.status.value}")
        if case.status.value != "pass":
            lines.append(f"       expected: {case.expected!r}")
            lines.append(f"       actual:   {case.actual!r}")
            if case.error:
                lines.append(f"       error:    {case.error.strip()}")
    workspace.results_path.write_text("\n".join(lines) + "\n")


@app.command("internal-review", hidden=True)
def internal_review(workspace_dir: Path) -> None:
    """Review the workspace solution and write review.md. Called by nvim."""
    from algorhythm.editor.session import workspace_from_dir
    from algorhythm.reviewer.ollama import OllamaReviewer
    from algorhythm.reviewer.protocol import ReviewerUnavailable, ReviewRequest

    workspace = workspace_from_dir(workspace_dir)
    problem = catalog.load_problem(workspace.slug)
    language = workspace.language

    solution = workspace.solution_path.read_text()
    cases = catalog.load_tests(workspace.slug)

    run_result = _execute(problem, workspace, cases)

    request = ReviewRequest(
        problem=problem,
        language=language,
        solution_source=solution,
        reference_source=_read(catalog.reference_path(workspace.slug, language)),
        run_result=run_result,
    )

    try:
        review = OllamaReviewer().review(request)
        body = review.text
        if review.proposed_grade:
            body += f"\n\n---\nProposed grade: **{review.proposed_grade.value}**"
            if review.grade_reason:
                body += f"\n{review.grade_reason}"
    except ReviewerUnavailable as exc:
        body = f"Review unavailable.\n\n{exc}"

    (workspace_dir / "review.md").write_text(body + "\n")


@app.command()
def review(
    limit: int = typer.Option(5, help="Maximum problems in today's queue."),
    new: int = typer.Option(2, help="Maximum unseen problems to introduce."),
) -> None:
    """Work through today's queue."""
    from algorhythm.tui.app import run_queue

    repo = _repo()
    queue = build_queue(
        repo,
        catalog.list_slugs(),
        _now(),
        QueueConfig(daily_cap=limit, new_per_day=new),
    )
    if not queue:
        typer.echo("Nothing due. Enjoy the day off.")
        raise typer.Exit()

    run_queue(queue, repo)


if __name__ == "__main__":
    app()
