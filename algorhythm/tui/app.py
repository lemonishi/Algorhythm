"""Textual presentation. All logic lives in session.py."""

from __future__ import annotations

from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from algorhythm.catalog import store as catalog
from algorhythm.catalog.models import LANGUAGES
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

    # The grades are a row, so h and l are the motions that fit. Arrows
    # keep working: the vim keys are additions, not replacements.
    BINDINGS = [
        Binding("left,h", "move(-1)", "Previous"),
        Binding("right,l", "move(1)", "Next"),
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


class TopicScreen(App):
    """Pick the topics to practise.

    A list rather than a text box: LeetCode's vocabulary is not obvious —
    its graph tag reads `Graph Theory` — and the point of choosing topics
    here instead of on the command line is not having to know the names
    before you start. Ordered by how many problems carry each, so the
    topics worth a session are at the top.
    """

    CSS = "#hint { padding: 0 2; color: $text-muted; }"

    BINDINGS = [
        Binding("escape,h", "cancel", "Cancel"),
        Binding("j", "cursor_down", "Down"),
        Binding("k", "cursor_up", "Up"),
        Binding("space,l", "toggle", "Toggle"),
        Binding("enter", "apply", "Apply"),
        Binding("c", "clear", "Everything"),
    ]

    def __init__(self, counts: dict[str, int], selected: list[str]) -> None:
        super().__init__()
        self._counts = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        self._selected = {
            name for name, _ in self._counts if name in set(selected)
        }
        self._labels: list[tuple[str, int, Label]] = []
        # None means "left the filter alone", which is a different answer
        # from the empty list — that one means "show me everything".
        self.result: list[str] | None = None

    # Not `[x]`: Rich reads square brackets as markup, so the marker parses
    # as a style tag and is stripped — leaving a selected row rendering
    # identically to an unselected one.
    SELECTED = "✓"
    UNSELECTED = "·"

    def _row(self, name: str, count: int) -> str:
        marker = self.SELECTED if name in self._selected else self.UNSELECTED
        return f"{marker} {name}  ({count})"

    def compose(self) -> ComposeResult:
        yield Header()
        items = []
        for name, count in self._counts:
            label = Label(self._row(name, count))
            self._labels.append((name, count, label))
            items.append(ListItem(label))
        yield ListView(*items)
        yield Static(
            "space toggles · enter applies · c for everything · esc cancels",
            id="hint",
        )
        yield Footer()

    def _highlighted(self) -> int | None:
        return self.query_one(ListView).index

    def action_cursor_down(self) -> None:
        self.query_one(ListView).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(ListView).action_cursor_up()

    def action_toggle(self) -> None:
        index = self._highlighted()
        if index is None:
            return
        name, count, label = self._labels[index]
        if name in self._selected:
            self._selected.discard(name)
        else:
            self._selected.add(name)
        label.update(self._row(name, count))

    def action_apply(self) -> None:
        chosen = [name for name, _, _ in self._labels if name in self._selected]
        # Toggling to pick a single topic is a step nobody should have to
        # take, so enter on a highlighted row means that row.
        index = self._highlighted()
        if not chosen and index is not None:
            chosen = [self._labels[index][0]]
        self.result = chosen
        self.exit()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.action_apply()

    def action_clear(self) -> None:
        self.result = []
        self.exit()

    def action_cancel(self) -> None:
        self.result = None
        self.exit()


class QueueScreen(App):
    """Shows today's queue and returns the chosen index."""

    CSS = """
    #note { padding: 0 2; color: $text-muted; }
    #topics { padding: 0 2; color: $accent; }
    """

    # j/k walk the list and l opens the highlighted problem, the way they
    # move in vim. Arrows, enter and escape are untouched.
    BINDINGS = [
        Binding("escape,h", "quit_queue", "Quit"),
        Binding("j", "cursor_down", "Down"),
        Binding("k", "cursor_up", "Up"),
        Binding("l", "open", "Open"),
        Binding("f", "filter", "Topics"),
    ]

    def __init__(
        self,
        rows: list[str],
        note: str | None = None,
        topics: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._rows = rows
        self._note = note
        self._topics = list(topics or [])
        self.chosen: int | None = None
        self.wants_filter = False

    def compose(self) -> ComposeResult:
        yield Header()
        # Without this a filtered queue looks like a short one, and there is
        # nothing on screen to say why today is quiet.
        if self._topics:
            yield Static(f"topics: {', '.join(self._topics)}", id="topics")
        yield ListView(*(ListItem(Label(row)) for row in self._rows))
        # Shown here rather than printed before launch: Textual takes the
        # whole screen, so anything echoed beforehand is wiped before it
        # can be read.
        if self._note:
            yield Static(self._note, id="note")
        yield Footer()

    def action_filter(self) -> None:
        self.wants_filter = True
        self.exit()

    def _list(self) -> ListView:
        return self.query_one(ListView)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.chosen = event.list_view.index
        self.exit()

    def action_cursor_down(self) -> None:
        self._list().action_cursor_down()

    def action_cursor_up(self) -> None:
        self._list().action_cursor_up()

    def action_open(self) -> None:
        self.chosen = self._list().index
        self.exit()

    def action_quit_queue(self) -> None:
        self.chosen = None
        self.exit()


def run_queue(
    queue,
    repo,
    *,
    language: str | None = None,
    note: str | None = None,
    rebuild=None,
    topics: list[str] | None = None,
) -> None:
    """Drive the queue to completion. Imported lazily by the CLI so a plain
    `algorhythm list` never pays Textual's import cost.

    `language` is the `--lang` override; it outranks history for every rep
    in this session (spec 10.3).

    `rebuild(topics)` returns a fresh queue for a set of topics. Picking
    topics has to rebuild rather than filter what is on screen: the reason
    to choose a topic is to practise something today's selection did not
    offer, and no amount of filtering a five-row list will produce it.
    """
    from algorhythm.editor.session import launch, prepare_workspace
    from algorhythm.reviewer.ollama import OllamaReviewer
    from algorhythm.runner.cpp_runner import run_cpp
    from algorhythm.runner.python_runner import run_python
    from algorhythm.session import RepDeps, persist, run_rep

    if language is not None and language not in LANGUAGES:
        raise ValueError(f"unknown language: {language!r}")

    remaining = list(queue)
    active = list(topics or [])
    # `or active` so a filter that matches nothing still shows the screen —
    # otherwise the session ends silently and the filter cannot be undone.
    while remaining or active:
        rows = []
        unloadable: set[str] = set()
        for entry in remaining:
            # A single malformed meta.json anywhere in today's queue used to
            # crash this loop before the first rep started. It is listed as
            # unusable instead, and dropped if picked.
            try:
                problem = catalog.load_problem(entry.slug)
            except Exception as exc:  # noqa: BLE001 - shown, never fatal
                unloadable.add(entry.slug)
                rows.append(f"{'unusable':>9}  {entry.slug} — {exc}")
                continue
            rows.append(format_queue_row(entry, problem.title, problem.difficulty))

        picker = QueueScreen(rows, note, active)
        picker.run()

        if picker.wants_filter:
            if rebuild is None:
                continue
            chooser = TopicScreen(catalog.all_topics(), active)
            chooser.run()
            if chooser.result is not None:  # None means cancelled
                active = chooser.result
                remaining = list(rebuild(active))
                note = None  # it described the queue we just replaced
            continue

        if picker.chosen is None:
            return

        item = remaining.pop(picker.chosen)
        if item.slug in unloadable:
            continue  # nothing to open; the row said why
        # Spec 10.3, in order: the flag, then the previous rep's language,
        # then the configured default.
        rep_language = language or repo.last_language(item.slug) or "python"

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
            prepare=lambda problem, lang, stub: prepare_workspace(
                problem, lang, stub=stub
            ),
            launch=launch,
            run_tests=lambda problem, workspace, cases: (
                run_python if workspace.language == "python" else run_cpp
            )(problem, workspace.solution_path, cases),
            reviewer=OllamaReviewer(),
            now=lambda: datetime.now(tz=timezone.utc),
            ask_grade=ask_grade,
            language=rep_language,
        )

        outcome = run_rep(item, deps)
        persist(outcome, repo, datetime.now(tz=timezone.utc))


def _read_optional(path) -> str | None:
    return path.read_text() if path.exists() else None
