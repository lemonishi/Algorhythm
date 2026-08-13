from dataclasses import replace
from datetime import datetime, timezone

import pytest

from algorhythm.catalog.models import Example, ParamSpec, Problem, TestCase
from algorhythm.catalog.store import list_slugs, load_problem
from algorhythm.seed import (
    neetcode_reference_urls,
    read_slug_list,
    seed_problems,
)

NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)


def problem(slug="two-sum", number=1) -> Problem:
    return Problem(
        slug=slug,
        number=number,
        title=slug.replace("-", " ").title(),
        difficulty="Easy",
        topics=[],
        companies=[],
        url="",
        statement_md="statement",
        constraints=[],
        examples=[],
        params=[ParamSpec("nums")],
        return_kind="raw",
        entry_point="solve",
        fetched_at=NOW,
    )


def fake_fetch(slug):
    if slug == "explodes":
        raise RuntimeError("404 from LeetCode")
    return problem(slug, number=abs(hash(slug)) % 900 + 1)


def with_examples() -> Problem:
    """A problem carrying the example case its statement shows."""
    return replace(
        problem("two-sum", number=1),
        examples=[Example(input_text="nums = [1,2,3]", output_text="6")],
        example_cases=[
            TestCase(
                id="example-1", args={"nums": [1, 2, 3]}, expected=6, source="example"
            )
        ],
    )


def real_reference(number, slug, language):
    """A reference the oracle can actually run, so oracle cases get made."""
    if language == "python":
        return "class Solution:\n    def solve(self, nums):\n        return sum(nums)\n"
    return "// no cpp reference needed here"


def fake_reference(number, slug, language):
    if slug == "no-reference":
        return None
    return f"# {language} reference for {slug}"


def exploding_reference(number, slug, language):
    if slug == "poisoned":
        raise RuntimeError("network blew up mid-reference")
    return fake_reference(number, slug, language)


# -- slug list ------------------------------------------------------------

def test_reads_one_slug_per_line(tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("two-sum\nvalid-anagram\n")
    assert read_slug_list(path) == ["two-sum", "valid-anagram"]


def test_ignores_comments_and_blank_lines(tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("# heading\n\ntwo-sum\n   \n# another\nvalid-anagram\n")
    assert read_slug_list(path) == ["two-sum", "valid-anagram"]


def test_strips_surrounding_whitespace(tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("  two-sum  \n")
    assert read_slug_list(path) == ["two-sum"]


# -- reference URLs -------------------------------------------------------

def test_reference_urls_cover_both_languages():
    urls = neetcode_reference_urls(102, "binary-tree-level-order-traversal")
    assert set(urls) == {"python", "cpp"}


def test_reference_urls_use_the_zero_padded_number():
    urls = neetcode_reference_urls(1, "two-sum")
    assert any("0001-two-sum" in url for url in urls["python"])


def test_reference_urls_offer_more_than_one_candidate_layout():
    """The upstream repo has reorganised before; try several paths and let
    the caller report which problems came up empty."""
    assert len(neetcode_reference_urls(1, "two-sum")["python"]) > 1


# -- seeding --------------------------------------------------------------

def test_seeds_each_slug(tmp_path):
    report = seed_problems(
        ["two-sum", "valid-anagram"],
        fetch=fake_fetch,
        fetch_reference=fake_reference,
        root=tmp_path,
    )
    assert report.added == ["two-sum", "valid-anagram"]
    assert sorted(list_slugs(root=tmp_path)) == ["two-sum", "valid-anagram"]


def test_writes_reference_solutions_for_both_languages(tmp_path):
    seed_problems(
        ["two-sum"], fetch=fake_fetch, fetch_reference=fake_reference, root=tmp_path
    )
    directory = next(tmp_path.iterdir())
    assert (directory / "reference.py").exists()
    assert (directory / "reference.cpp").exists()


def test_reports_problems_that_got_no_reference(tmp_path):
    report = seed_problems(
        ["no-reference"],
        fetch=fake_fetch,
        fetch_reference=fake_reference,
        root=tmp_path,
    )
    assert report.missing_reference == ["no-reference"]


def test_a_problem_without_a_reference_is_still_added(tmp_path):
    """Losing the reference costs you comparison, not the problem itself."""
    report = seed_problems(
        ["no-reference"],
        fetch=fake_fetch,
        fetch_reference=fake_reference,
        root=tmp_path,
    )
    assert "no-reference" in report.added


def test_a_fetch_failure_is_recorded_and_does_not_stop_the_run(tmp_path):
    report = seed_problems(
        ["two-sum", "explodes", "valid-anagram"],
        fetch=fake_fetch,
        fetch_reference=fake_reference,
        root=tmp_path,
    )
    assert [slug for slug, _ in report.failed] == ["explodes"]
    assert report.added == ["two-sum", "valid-anagram"]


def test_already_present_problems_are_skipped(tmp_path):
    kwargs = dict(fetch=fake_fetch, fetch_reference=fake_reference, root=tmp_path)
    seed_problems(["two-sum"], **kwargs)
    report = seed_problems(["two-sum"], **kwargs)
    assert report.skipped == ["two-sum"]
    assert report.added == []


def test_statement_survives_the_roundtrip(tmp_path):
    seed_problems(
        ["two-sum"], fetch=fake_fetch, fetch_reference=fake_reference, root=tmp_path
    )
    assert load_problem("two-sum", root=tmp_path).statement_md == "statement"


def test_a_raising_fetch_reference_does_not_abort_the_run(tmp_path):
    report = seed_problems(
        ["poisoned", "two-sum"],
        fetch=fake_fetch,
        fetch_reference=exploding_reference,
        root=tmp_path,
    )
    assert "two-sum" in report.added
    assert [slug for slug, _ in report.failed] == ["poisoned"]


def test_example_cases_are_written_ahead_of_the_oracle_cases(tmp_path):
    """Spec 7.1: example cases plus oracle cases. The oracle deliberately
    excludes the seed value, so without the examples the case the user just
    read is not among the ones they are tested against."""
    from algorhythm.catalog.store import load_tests

    seed_problems(
        ["two-sum"],
        fetch=lambda slug: with_examples(),
        fetch_reference=real_reference,
        root=tmp_path,
    )
    cases = load_tests("two-sum", root=tmp_path)
    assert [c.source for c in cases][0] == "example"
    assert cases[0].args == {"nums": [1, 2, 3]}
    assert cases[0].expected == 6
    assert "oracle" in {c.source for c in cases}


def test_example_cases_are_written_even_without_a_python_reference(tmp_path):
    """No reference means no oracle cases; the examples still have stated
    expected outputs, so the correctness signal survives."""
    from algorhythm.catalog.store import load_tests

    seed_problems(
        ["two-sum"],
        fetch=lambda slug: with_examples(),
        fetch_reference=lambda number, slug, language: None,
        root=tmp_path,
    )
    cases = load_tests("two-sum", root=tmp_path)
    assert [c.source for c in cases] == ["example"]


def test_a_problem_whose_examples_would_not_parse_is_reported(tmp_path):
    """Silence here is what hides a `0/0 passed` rep, so it goes in the
    report rather than nowhere."""
    report = seed_problems(
        ["two-sum"],
        fetch=lambda slug: replace(with_examples(), example_cases=[]),
        fetch_reference=lambda number, slug, language: None,
        root=tmp_path,
    )
    assert report.no_example_cases == ["two-sum"]
    assert "example" in report.render()


def test_a_problem_with_no_examples_at_all_is_not_reported_as_a_failure(tmp_path):
    report = seed_problems(
        ["two-sum"], fetch=fake_fetch, fetch_reference=fake_reference, root=tmp_path
    )
    assert report.no_example_cases == []


def test_a_rolled_back_problem_leaves_no_directory(tmp_path):
    seed_problems(
        ["poisoned", "two-sum"],
        fetch=fake_fetch,
        fetch_reference=exploding_reference,
        root=tmp_path,
    )
    assert "poisoned" not in list_slugs(root=tmp_path)
    assert not any(tmp_path.glob("*-poisoned"))


def test_a_rolled_back_problem_is_retryable(tmp_path):
    seed_problems(
        ["poisoned"], fetch=fake_fetch, fetch_reference=exploding_reference, root=tmp_path
    )
    report = seed_problems(
        ["poisoned"], fetch=fake_fetch, fetch_reference=fake_reference, root=tmp_path
    )
    assert report.added == ["poisoned"]
    assert report.skipped == []


def test_a_duplicate_slug_within_one_list_is_seeded_once(tmp_path):
    report = seed_problems(
        ["two-sum", "two-sum"],
        fetch=fake_fetch,
        fetch_reference=fake_reference,
        root=tmp_path,
    )
    assert report.added == ["two-sum"]
    assert report.skipped == ["two-sum"]


def test_a_raising_save_problem_does_not_abort_the_run(tmp_path, monkeypatch):
    """save_problem itself, not just what comes after it, must be inside the
    guarded region: a failure there is the identical defect one statement
    earlier."""
    import algorhythm.seed as seed_module

    original_save_problem = seed_module.catalog.save_problem

    def flaky_save_problem(problem, root=None):
        if problem.slug == "poisoned":
            raise OSError("disk full")
        return original_save_problem(problem, root=root)

    monkeypatch.setattr(seed_module.catalog, "save_problem", flaky_save_problem)

    report = seed_problems(
        ["poisoned", "two-sum"],
        fetch=fake_fetch,
        fetch_reference=fake_reference,
        root=tmp_path,
    )
    assert "two-sum" in report.added
    assert [slug for slug, _ in report.failed] == ["poisoned"]


def test_a_partial_save_problem_leaves_nothing_behind(tmp_path, monkeypatch):
    """Simulates the realistic failure shape: save_problem writes meta.json
    (its first file) and then dies before finishing. list_slugs must not be
    able to see this problem as present afterwards."""
    import algorhythm.seed as seed_module

    def flaky_save_problem(problem, root=None):
        directory = seed_module.catalog.problem_dir(problem, root=root)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "meta.json").write_text("{}")
        raise OSError("disk full after writing meta.json")

    monkeypatch.setattr(seed_module.catalog, "save_problem", flaky_save_problem)

    seed_problems(
        ["poisoned"], fetch=fake_fetch, fetch_reference=fake_reference, root=tmp_path
    )
    assert "poisoned" not in list_slugs(root=tmp_path)
    assert not any(tmp_path.glob("*-poisoned"))
