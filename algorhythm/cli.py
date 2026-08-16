"""Typer entry point.

`internal-test` and `internal-review` are called by the nvim Lua module,
not by humans; they read a workspace directory and write their output to a
file the editor then reloads.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import typer

from algorhythm import config
from algorhythm.catalog import store as catalog
from algorhythm.catalog.models import LANGUAGES
from algorhythm.runner.cpp_runner import run_cpp
from algorhythm.runner.python_runner import run_python
from algorhythm.scheduler.queue import (
    QueueConfig,
    build_queue,
    held_back_by_new_cap,
)
from algorhythm.store.db import connect
from algorhythm.store.repository import Repository

app = typer.Typer(add_completion=False, help="Spaced repetition for DSA interviews.")


@contextmanager
def _repo() -> Iterator[Repository]:
    """Own the connection for the length of one command.

    A process-lifetime connection would work in production, but it also
    leaves an unclosed handle behind for anything that invokes a command
    in-process — which surfaces as a ResourceWarning attributed to whatever
    test happens to run next.
    """
    conn = connect(config.db_path())
    try:
        yield Repository(conn)
    finally:
        conn.close()


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
    with _repo() as repo:
        for slug in catalog.list_slugs():
            row = repo.get_schedule(slug)
            when = row.due_at.date().isoformat() if row else "unseen"
            reps = row.state.reps if row else 0
            typer.echo(f"{when:>10}  reps={reps:<3} {slug}")


@app.command()
def stats() -> None:
    """Counts of scheduled problems, reviews, and attempts."""
    with _repo() as repo:
        for key, value in repo.counts().items():
            typer.echo(f"{key:>10}: {value}")


@app.command()
def topics() -> None:
    """List the topics in the library, with how many problems carry each."""
    counts = catalog.all_topics()
    if not counts:
        typer.echo("No problems yet — run `algorhythm seed` first.")
        return
    width = max(len(name) for name in counts)
    for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        typer.echo(f"{name:<{width}}  {count}")


@app.command()
def add(slug: str) -> None:
    """Fetch a problem from LeetCode and add it to the library."""
    from algorhythm.catalog.fetch import fetch_question
    from algorhythm import seed as seed_module

    # Deliberately the same path as `seed`, rather than a fetch-and-save of
    # its own. Saving the problem alone leaves it with no reference solution
    # and no test cases, which is a rep that cannot be run or reviewed —
    # and any drift between the two commands shows up as exactly that.
    report = seed_module.seed_problems(
        [slug],
        fetch=fetch_question,
        fetch_reference=seed_module.fetch_reference_from_github,
    )
    typer.echo(report.render())
    if report.failed:
        raise typer.Exit(1)


@app.command()
def seed(
    list_path: Path = typer.Option(
        Path("seeds/neetcode150.txt"), help="File of LeetCode slugs, one per line."
    ),
) -> None:
    """Bulk-fetch a curated list and import reference solutions."""
    from algorhythm.catalog.fetch import fetch_question
    from algorhythm.seed import (
        fetch_reference_from_github,
        read_slug_list,
        seed_problems,
    )

    slugs = read_slug_list(list_path)
    typer.echo(f"seeding {len(slugs)} problems — this hits the network, be patient")

    report = seed_problems(
        slugs,
        fetch=fetch_question,
        fetch_reference=fetch_reference_from_github,
    )
    typer.echo(report.render())


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
    limit: int = typer.Option(
        5, min=1, help="Maximum problems in today's queue."
    ),
    new: int = typer.Option(
        2, min=0, help="Maximum unseen problems to introduce."
    ),
    topic: list[str] = typer.Option(
        None,
        "--topic",
        "-t",
        help="Only problems carrying this topic; repeatable. Any match "
        "counts, so several topics widen the session rather than narrow it. "
        "See `algorhythm topics`.",
    ),
    lang: str = typer.Option(
        None,
        "--lang",
        help="Language for every rep in this session (python or cpp). "
        "Defaults to the language of each problem's previous rep.",
    ),
) -> None:
    """Work through today's queue."""
    from algorhythm.tui.app import run_queue

    # Checked before any I/O so a typo costs nothing and says what to type.
    if lang is not None and lang not in LANGUAGES:
        typer.secho(
            f"unknown language: {lang!r} — choose from "
            f"{', '.join(sorted(LANGUAGES))}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(2)

    # Checked before opening the database: a typo selects nothing, and an
    # empty queue reads exactly like a finished one.
    if topic:
        unknown = catalog.unknown_topics(list(topic))
        if unknown:
            available = ", ".join(sorted(catalog.all_topics()))
            typer.secho(
                f"unknown topic: {', '.join(unknown)}\n\nAvailable: {available}",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(2)

    with _repo() as repo:
        config = QueueConfig(daily_cap=limit, new_per_day=new)
        slugs = catalog.list_slugs()
        if topic:
            slugs = catalog.select_by_topic(slugs, list(topic))
        queue = build_queue(repo, slugs, _now(), config)
        if not queue:
            typer.echo("Nothing due. Enjoy the day off.")
            raise typer.Exit()

        # `--limit` is the flag people reach for, and on an all-new library
        # it changes nothing: the new-per-day cap is what is binding. Say so
        # and name the flag that does work.
        note = None
        if held_back_by_new_cap(repo, slugs, config, queue):
            note = (
                f"Showing {len(queue)} — `--new {new}` caps how many unseen "
                f"problems are introduced per day. More unseen problems are "
                f"waiting: use `--new {limit}` to fill today's queue."
            )

        run_queue(queue, repo, language=lang, note=note)


if __name__ == "__main__":
    app()
