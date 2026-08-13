"""One rep, end to end, with only nvim and Ollama faked.

Every unit in this codebase passed while the assembly was broken: the stub
was fetched and thrown away, so every rep opened an empty buffer; C++ was
unreachable; and no example case was ever generated. Each of those is
invisible to a unit test and obvious here.

So this exercises the real chain — parse a recorded GraphQL response, seed a
real problem directory, resolve the stub through catalog.stub_path, prepare
a real workspace, run the real runner over the real tests.json, and grade —
faking only the two things that need a human or a daemon.

No network: the payload comes from the recorded fixture and the reference
solutions are local strings.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from algorhythm.catalog import store as catalog
from algorhythm.catalog.fetch import parse_question
from algorhythm.editor.session import prepare_workspace
from algorhythm.reviewer.protocol import ReviewerUnavailable
from algorhythm.runner.cpp_runner import run_cpp
from algorhythm.runner.python_runner import run_python
from algorhythm.scheduler.queue import QueueItem
from algorhythm.scheduler.sm2 import NEW, Grade
from algorhythm.seed import seed_problems
from algorhythm.session import RepDeps, persist, run_rep
from algorhythm.store.db import connect
from algorhythm.store.repository import Repository

FIXTURES = Path(__file__).parent / "catalog" / "fixtures"
NOW = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
SLUG = "binary-tree-level-order-traversal"

PYTHON_REFERENCE = """
class Solution:
    def levelOrder(self, root):
        levels = []
        frontier = [root] if root else []
        while frontier:
            levels.append([node.val for node in frontier])
            frontier = [
                child
                for node in frontier
                for child in (node.left, node.right)
                if child
            ]
        return levels
"""

CPP_REFERENCE = """
class Solution {
public:
    vector<vector<int>> levelOrder(TreeNode* root) {
        vector<vector<int>> levels;
        if (!root) return levels;
        vector<TreeNode*> frontier{root};
        while (!frontier.empty()) {
            vector<int> vals;
            vector<TreeNode*> next;
            for (TreeNode* node : frontier) {
                vals.push_back(node->val);
                if (node->left) next.push_back(node->left);
                if (node->right) next.push_back(node->right);
            }
            levels.push_back(vals);
            frontier = next;
        }
        return levels;
    }
};
"""


class DeadReviewer:
    """Ollama is not running — spec 11 says the rep completes anyway."""

    def review(self, request):
        raise ReviewerUnavailable("connection refused")


@pytest.fixture
def library(tmp_path, monkeypatch):
    """A seeded problem directory, built the way `algorhythm seed` builds it."""
    monkeypatch.setenv("ALGORHYTHM_HOME", str(tmp_path / "home"))
    root = tmp_path / "problems"
    payload = json.loads((FIXTURES / "level_order.json").read_text())

    def fetch(slug):
        return parse_question(payload, fetched_at=NOW)

    def fetch_reference(number, slug, language):
        return PYTHON_REFERENCE if language == "python" else CPP_REFERENCE

    report = seed_problems(
        [SLUG], fetch=fetch, fetch_reference=fetch_reference, root=root
    )
    assert report.failed == [], report.failed
    return root


def rep(library, language, edit) -> tuple:
    """Run one full rep. `edit` plays the part of the user in nvim."""
    seen: dict = {}

    def launch(workspace):
        # nvim's stand-in. What it sees on entry is what the user would see.
        seen["seeded"] = workspace.solution_path.read_text()
        workspace.solution_path.write_text(edit)
        return 0

    deps = RepDeps(
        load_problem=lambda slug: catalog.load_problem(slug, root=library),
        load_tests=lambda slug: catalog.load_tests(slug, root=library),
        reference_source=lambda slug, lang: catalog.reference_path(
            slug, lang, root=library
        ).read_text(),
        stub_source=lambda slug, lang: catalog.stub_path(
            slug, lang, root=library
        ).read_text(),
        prepare=lambda problem, lang, stub, previous: prepare_workspace(
            problem, lang, stub=stub, previous_attempt=previous
        ),
        launch=launch,
        run_tests=lambda problem, workspace, cases: (
            run_python if workspace.language == "python" else run_cpp
        )(problem, workspace.solution_path, cases),
        reviewer=DeadReviewer(),
        now=lambda: NOW,
        ask_grade=lambda review, run_result: Grade.GOOD,
        language=language,
    )
    outcome = run_rep(
        QueueItem(slug=SLUG, is_new=True, due_at=None, state=NEW), deps
    )
    return outcome, seen


# -- seeding produced something usable ------------------------------------


def test_seeding_writes_the_stub_the_rep_will_open(library):
    assert catalog.stub_path(SLUG, "python", root=library).exists()
    assert catalog.stub_path(SLUG, "cpp", root=library).exists()


def test_seeding_writes_example_cases_alongside_the_oracle_ones(library):
    cases = catalog.load_tests(SLUG, root=library)
    sources = [c.source for c in cases]
    assert "example" in sources and "oracle" in sources
    example = next(c for c in cases if c.source == "example")
    assert example.args == {"root": [3, 9, 20, None, None, 15, 7]}
    assert example.expected == [[3], [9, 20], [15, 7]]


# -- the rep itself --------------------------------------------------------


def test_a_python_rep_opens_a_seeded_buffer_and_runs_real_cases(library):
    outcome, seen = rep(library, "python", PYTHON_REFERENCE)

    # Critical 1: the buffer the user lands in carries the real signature.
    assert "def levelOrder" in seen["seeded"]
    # Critical 3: cases actually ran, and the example is among them.
    assert outcome.run_result.total >= 2
    assert outcome.run_result.passed == outcome.run_result.total
    assert outcome.run_result.compile_error is None
    # Spec 11: a dead reviewer does not block the grade.
    assert outcome.review is None
    assert outcome.grade is Grade.GOOD


def test_a_wrong_python_solution_actually_fails_a_case(library):
    """Guards against the failure this whole test exists to catch: `0/0
    passed` reporting ok because no case was ever generated."""
    wrong = "class Solution:\n    def levelOrder(self, root):\n        return []\n"
    outcome, _ = rep(library, "python", wrong)
    assert outcome.run_result.total >= 2
    assert outcome.run_result.passed < outcome.run_result.total
    assert outcome.run_result.ok is False


def test_the_rep_persists_and_schedules(library):
    conn = connect(":memory:")
    try:
        repo = Repository(conn)
        outcome, _ = rep(library, "python", PYTHON_REFERENCE)
        persist(outcome, repo, NOW)

        assert repo.counts() == {"scheduled": 1, "reviews": 1, "attempts": 1}
        assert repo.get_schedule(SLUG).due_at > NOW
        # The language the rep ran in is what a later rep resolves against.
        assert repo.last_language(SLUG) == "python"
    finally:
        conn.close()


@pytest.mark.skipif(
    shutil.which("clang++") is None, reason="no clang++ on PATH"
)
def test_a_cpp_rep_opens_a_seeded_buffer_and_runs_real_cases(library):
    """Critical 2's other half: with the stub missing, the generated harness
    #includes an empty file, `Solution` is undeclared, and nothing compiles."""
    outcome, seen = rep(library, "cpp", CPP_REFERENCE)

    assert "class Solution" in seen["seeded"]
    assert outcome.run_result.compile_error is None, outcome.run_result.compile_error
    assert outcome.run_result.total >= 2
    assert outcome.run_result.passed == outcome.run_result.total
    assert outcome.grade is Grade.GOOD
