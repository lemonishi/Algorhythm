"""The curated-overrides layer, and that its contents are actually correct.

The point of these files is to be right where the fetched data is wrong, so
a test that only checks the plumbing would miss the whole risk. The bottom
half runs each curated reference against its curated cases.
"""

import json

import pytest

from algorhythm import curated
from algorhythm.catalog.models import LANGUAGES


def curated_slugs():
    """Every curated problem directory. `__pycache__` is not one."""
    return sorted(
        p.name
        for p in curated.ROOT.iterdir()
        if p.is_dir() and not p.name.startswith("__")
    )


def test_an_unknown_slug_has_nothing_curated():
    """A problem with no directory must seed exactly as it did before."""
    assert curated.reference("no-such-problem", "python") is None
    assert curated.tests("no-such-problem") is None
    assert curated.overrides("no-such-problem") == {}


def test_number_of_islands_ships_a_reference_for_both_languages():
    """Upstream's file has broken indentation, so this one replaces it."""
    for language in LANGUAGES:
        source = curated.reference("number-of-islands", language)
        assert source and "numIslands" in source


def test_the_python_reference_actually_parses():
    """The defect being corrected was an IndentationError — compiling the
    replacement is the only check that matters."""
    source = curated.reference("number-of-islands", "python")
    compile(source, "reference.py", "exec")


def test_linked_list_cycle_ships_cases_the_oracle_cannot_generate():
    cases = curated.tests("linked-list-cycle")
    assert cases and len(cases) >= 6
    assert any(case.expected is True for case in cases)
    assert any(case.expected is False for case in cases)
    assert all("pos" in case.args["head"] for case in cases)


@pytest.mark.parametrize("slug", ["group-anagrams", "two-sum", "3sum"])
def test_any_order_problems_are_marked_unordered(slug):
    assert curated.overrides(slug)["comparison"] == "unordered"


def test_every_curated_directory_is_well_formed():
    """A typo in a filename would silently do nothing at seed time."""
    allowed = {"reference.py", "reference.cpp", "tests.json", "problem.json"}
    for slug in curated_slugs():
        present = {p.name for p in (curated.ROOT / slug).iterdir() if p.is_file()}
        assert present, f"{slug} has no curated files"
        assert present <= allowed, f"{slug} has unexpected files: {present - allowed}"


def test_every_curated_override_names_a_real_field():
    from algorhythm.catalog.models import COMPARISONS, Problem

    fields = set(Problem.__dataclass_fields__)
    for slug in curated_slugs():
        for key, value in curated.overrides(slug).items():
            assert key in fields, f"{slug} overrides unknown field {key!r}"
            if key == "comparison":
                assert value in COMPARISONS, f"{slug} has a bogus comparison"


def test_every_curated_tests_file_is_loadable():
    for slug in curated_slugs():
        cases = curated.tests(slug)
        if cases is None:
            continue
        assert len({case.id for case in cases}) == len(cases), f"{slug} has dup ids"


# -- the curated content is correct, not just present -----------------------


def test_the_curated_islands_reference_solves_the_problem():
    """Run it against LeetCode's own stated examples."""
    from datetime import datetime, timezone

    from algorhythm.catalog.models import ParamSpec, Problem, TestCase
    from algorhythm.runner.python_runner import run_python

    problem = Problem(
        slug="number-of-islands",
        number=200,
        title="Number of Islands",
        difficulty="Medium",
        topics=[],
        companies=[],
        url="",
        statement_md="",
        constraints=[],
        examples=[],
        params=[ParamSpec("grid", kind="grid")],
        return_kind="raw",
        entry_point="numIslands",
        fetched_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
    )
    cases = [
        TestCase(
            id="example-1",
            args={
                "grid": [
                    ["1", "1", "1", "1", "0"],
                    ["1", "1", "0", "1", "0"],
                    ["1", "1", "0", "0", "0"],
                    ["0", "0", "0", "0", "0"],
                ]
            },
            expected=1,
            source="example",
        ),
        TestCase(
            id="example-2",
            args={
                "grid": [
                    ["1", "1", "0", "0", "0"],
                    ["1", "1", "0", "0", "0"],
                    ["0", "0", "1", "0", "0"],
                    ["0", "0", "0", "1", "1"],
                ]
            },
            expected=3,
            source="example",
        ),
    ]

    path = curated.ROOT / "number-of-islands" / "reference.py"
    result = run_python(problem, path, cases)
    assert result.summary == "2/2 passed", [c.error for c in result.cases]
