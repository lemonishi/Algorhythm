"""Textual presentation. All logic lives in session.py."""

from __future__ import annotations

from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from algorhythm.catalog import store as catalog
from algorhythm.reviewer.protocol import Review
from algorhythm.runner.harness import RunResult
from algorhythm.scheduler.sm2 import Grade
from algorhythm.tui.format import format_queue_row, format_results, grade_choices


class GradeScreen(App):
    """Shows the review and collects a grade. Enter accepts the highlighted
    option, arrows move, escape abandons the rep."""

    CSS = """
    #review { height: 1fr; border: round $accent; padding: 1 2; }
    #results { height: auto; max-height: 12; border: round $secondary; padding: 0 2; }
    #grades { height: auto; align: center middle; padding: 1; }
    .grade { padding: 0 3; }
    .selected { background: $accent; color: $text; text-style: bold; }
    """

    BINDINGS = [
        Binding("left", "move(-1)", "Previous"),
        Binding("right", "move(1)", "Next"),
        Binding("enter", "accept", "Accept"),
        Binding("escape", "abandon", "Skip"),
    ]

    def __init__(self, review: Review | None, run_result: RunResult) -> None:
        super().__init__()
        self._review = review
        self._run_result = run_result
        self._choices = grade_choices(review.proposed_grade if review else None)
        self._index = next(i for i, (_, sel) in enumerate(self._choices) if sel)
        self.result: Grade | None = None

    # -- test helpers -----------------------------------------------------

    @classmethod
    def host(cls, review: Review | None, run_result: RunResult) -> "GradeScreen":
        return cls(review, run_result)

    def screen_text(self) -> str:
        return " ".join(str(widget.render()) for widget in self.query(Static))

    # -- composition ------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        body = (
            self._review.text
            if self._review
            else "Review unavailable — Ollama could not be reached. Grade from "
            "your own sense of how the rep went."
        )
        with Vertical():
            yield Static(body, id="review")
            yield Static(format_results(self._run_result), id="results")
            with Horizontal(id="grades"):
                for index, (grade, _) in enumerate(self._choices):
                    classes = "grade selected" if index == self._index else "grade"
                    yield Label(grade.value, classes=classes, id=f"grade-{index}")
        yield Footer()

    # -- actions ----------------------------------------------------------

    def action_move(self, delta: int) -> None:
        self._index = (self._index + delta) % len(self._choices)
        for index in range(len(self._choices)):
            label = self.query_one(f"#grade-{index}", Label)
            label.set_classes("grade selected" if index == self._index else "grade")

    def action_accept(self) -> None:
        self.result = self._choices[self._index][0]
        self.exit()

    def action_abandon(self) -> None:
        self.result = None
        self.exit()


class QueueScreen(App):
    """Shows today's queue and returns the chosen index."""

    BINDINGS = [Binding("escape", "quit_queue", "Quit")]

    def __init__(self, rows: list[str]) -> None:
        super().__init__()
        self._rows = rows
        self.chosen: int | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield ListView(*(ListItem(Label(row)) for row in self._rows))
        yield Footer()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.chosen = event.list_view.index
        self.exit()

    def action_quit_queue(self) -> None:
        self.chosen = None
        self.exit()


def run_queue(queue, repo) -> None:
    """Drive the queue to completion. Imported lazily by the CLI so a plain
    `algorhythm list` never pays Textual's import cost."""
    from algorhythm.editor.session import launch, prepare_workspace
    from algorhythm.reviewer.ollama import OllamaReviewer
    from algorhythm.runner.cpp_runner import run_cpp
    from algorhythm.runner.python_runner import run_python
    from algorhythm.session import RepDeps, persist, run_rep

    remaining = list(queue)
    while remaining:
        rows = []
        for entry in remaining:
            problem = catalog.load_problem(entry.slug)
            rows.append(format_queue_row(entry, problem.title, problem.difficulty))

        picker = QueueScreen(rows)
        picker.run()
        if picker.chosen is None:
            return

        item = remaining.pop(picker.chosen)
        language = repo.last_language(item.slug) or "python"

        def ask_grade(review, run_result):
            screen = GradeScreen(review, run_result)
            screen.run()
            return screen.result

        deps = RepDeps(
            load_problem=catalog.load_problem,
            load_tests=catalog.load_tests,
            reference_source=lambda slug, lang: _read_optional(
                catalog.reference_path(slug, lang)
            ),
            stub_source=lambda slug, lang: _read_optional(
                catalog.stub_path(slug, lang)
            )
            or "",
            prepare=lambda problem, lang, stub, previous: prepare_workspace(
                problem, lang, stub=stub, previous_attempt=previous
            ),
            launch=launch,
            run_tests=lambda problem, workspace, cases: (
                run_python if workspace.language == "python" else run_cpp
            )(problem, workspace.solution_path, cases),
            reviewer=OllamaReviewer(),
            now=lambda: datetime.now(tz=timezone.utc),
            ask_grade=ask_grade,
            load_previous_attempt=repo.last_attempt_source,
            language=language,
        )

        outcome = run_rep(item, deps)
        persist(outcome, repo, datetime.now(tz=timezone.utc))


def _read_optional(path) -> str | None:
    return path.read_text() if path.exists() else None
