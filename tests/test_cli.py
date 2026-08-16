"""CLI wiring. The queue itself is stubbed out; what is under test here is
the plumbing between the command's options and `run_queue`."""

from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from algorhythm import cli
from algorhythm.scheduler.queue import QueueItem
from algorhythm.scheduler.sm2 import NEW

NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)

runner = CliRunner()


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ALGORHYTHM_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def captured_queue(monkeypatch):
    """Stub `run_queue` and hand back whatever it was called with."""
    import algorhythm.tui.app as tui_app

    captured: dict = {}

    def fake_run_queue(queue, repo, *args, **kwargs):
        captured["queue"] = queue
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.setattr(tui_app, "run_queue", fake_run_queue)
    monkeypatch.setattr(
        cli,
        "build_queue",
        lambda repo, slugs, now, config: [
            QueueItem(slug="two-sum", is_new=True, due_at=None, state=NEW)
        ],
    )
    return captured


def test_lang_option_reaches_run_queue(isolated_home, captured_queue):
    """Spec 10.3 resolution order starts with `--lang`. Without this the
    chain is circular and C++ is unreachable."""
    result = runner.invoke(cli.app, ["review", "--lang", "cpp"])
    assert result.exit_code == 0, result.output
    assert captured_queue["kwargs"].get("language") == "cpp"


def test_lang_defaults_to_none_so_history_decides(isolated_home, captured_queue):
    result = runner.invoke(cli.app, ["review"])
    assert result.exit_code == 0, result.output
    assert captured_queue["kwargs"].get("language") is None


def test_unknown_lang_is_rejected_with_a_clear_message(isolated_home, captured_queue):
    result = runner.invoke(cli.app, ["review", "--lang", "rust"])
    assert result.exit_code != 0
    assert "rust" in result.output
    assert "unknown language" in result.output.lower()
    assert "queue" not in captured_queue


def test_limit_must_be_positive(isolated_home, captured_queue):
    """`--limit -1` is `LIMIT -1` in SQLite, i.e. unbounded — the exact
    thing the daily cap exists to prevent."""
    result = runner.invoke(cli.app, ["review", "--limit", "-1"])
    assert result.exit_code != 0
    assert "queue" not in captured_queue


def test_new_may_be_zero_but_not_negative(isolated_home, captured_queue):
    assert runner.invoke(cli.app, ["review", "--new", "0"]).exit_code == 0
    assert runner.invoke(cli.app, ["review", "--new", "-1"]).exit_code != 0


# -- add --------------------------------------------------------------------


def test_add_goes_through_the_same_path_as_seed(monkeypatch, tmp_path):
    """`add` must produce a usable problem, not a statement on its own.

    Saving the fetched problem and stopping there leaves no reference and no
    test cases, so the rep opens, reports `0/0 passed`, and the review has
    nothing to compare against — the exact degraded state the seeding
    pipeline exists to prevent.
    """
    import algorhythm.seed as seed_module

    seen = {}

    def fake_seed_problems(slugs, *, fetch, fetch_reference, root=None):
        seen["slugs"] = slugs
        seen["fetch_reference"] = fetch_reference
        return seed_module.SeedReport(added=list(slugs))

    monkeypatch.setattr(seed_module, "seed_problems", fake_seed_problems)

    result = runner.invoke(cli.app, ["add", "two-sum"])

    assert result.exit_code == 0, result.output
    assert seen["slugs"] == ["two-sum"]
    # The reference fetcher has to be wired, or there is no comparison and
    # no oracle — which is most of what a seeded problem is for.
    assert seen["fetch_reference"] is seed_module.fetch_reference_from_github


def test_add_reports_a_failure_and_exits_non_zero(monkeypatch):
    import algorhythm.seed as seed_module

    def fake_seed_problems(slugs, **kwargs):
        return seed_module.SeedReport(failed=[(slugs[0], "question not found")])

    monkeypatch.setattr(seed_module, "seed_problems", fake_seed_problems)

    result = runner.invoke(cli.app, ["add", "no-such-problem"])

    assert result.exit_code == 1
    assert "question not found" in result.output


# -- topics -----------------------------------------------------------------


def test_topics_lists_what_the_library_carries(monkeypatch):
    monkeypatch.setattr(
        cli.catalog, "all_topics", lambda: {"Array": 12, "Graph": 3}
    )
    result = runner.invoke(cli.app, ["topics"])
    assert result.exit_code == 0
    assert "Array" in result.output and "12" in result.output


def test_topics_says_so_when_the_library_is_empty(monkeypatch):
    monkeypatch.setattr(cli.catalog, "all_topics", lambda: {})
    result = runner.invoke(cli.app, ["topics"])
    assert result.exit_code == 0
    assert "seed" in result.output.lower()


def test_an_unknown_topic_is_refused_before_any_work(monkeypatch):
    """An empty queue from a typo is indistinguishable from a finished one."""
    monkeypatch.setattr(cli.catalog, "unknown_topics", lambda wanted: ["arrys"])
    monkeypatch.setattr(cli.catalog, "all_topics", lambda: {"Array": 1})

    result = runner.invoke(cli.app, ["review", "--topic", "arrys"])

    assert result.exit_code == 2
    assert "arrys" in result.output
    assert "Array" in result.output  # says what it could have meant


def test_a_topic_narrows_the_catalog_the_queue_is_built_from(monkeypatch):
    seen = {}

    monkeypatch.setattr(cli.catalog, "unknown_topics", lambda wanted: [])
    monkeypatch.setattr(cli.catalog, "list_slugs", lambda: ["a", "b", "c"])
    monkeypatch.setattr(
        cli.catalog, "select_by_topic", lambda slugs, wanted: ["b"]
    )

    def fake_build_queue(repo, slugs, now, config):
        seen["slugs"] = slugs
        return []

    monkeypatch.setattr(cli, "build_queue", fake_build_queue)

    result = runner.invoke(cli.app, ["review", "--topic", "graph"])

    assert seen["slugs"] == ["b"], result.output


def test_no_topic_flag_uses_the_whole_catalog(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.catalog, "list_slugs", lambda: ["a", "b", "c"])

    def fake_build_queue(repo, slugs, now, config):
        seen["slugs"] = slugs
        return []

    monkeypatch.setattr(cli, "build_queue", fake_build_queue)
    runner.invoke(cli.app, ["review"])
    assert seen["slugs"] == ["a", "b", "c"]
