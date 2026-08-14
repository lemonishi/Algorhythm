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
