from datetime import datetime, timezone

import pytest

from algorhythm.catalog.models import ParamSpec, Problem
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


def fake_reference(number, slug, language):
    if slug == "no-reference":
        return None
    return f"# {language} reference for {slug}"


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
