"""Bulk library seeding.

Fetches each problem, imports a reference solution from neetcode-gh, and
generates oracle test cases. Nothing here aborts the whole run: a problem
that fails to fetch, or that has no available reference, is recorded and
the run continues. The report is the deliverable — it tells you exactly
which problems need hand-written references before their reviews mean
anything.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from algorhythm.catalog import store as catalog
from algorhythm.catalog.models import LANGUAGES, Problem
from algorhythm.oracle import generate_oracle_cases

RAW_BASE = "https://raw.githubusercontent.com/neetcode-gh/leetcode/main"

_LANGUAGE_DIRS = {"python": ("python", "py"), "cpp": ("cpp", "cpp")}


def read_slug_list(path: Path) -> list[str]:
    lines = path.read_text().splitlines()
    return [
        stripped
        for line in lines
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]


def neetcode_reference_urls(number: int, slug: str) -> dict[str, list[str]]:
    """Candidate raw URLs per language.

    The upstream repository has reorganised its layout before, so each
    language gets several candidates tried in order rather than one guess.
    """
    padded = f"{number:04d}"
    out: dict[str, list[str]] = {}
    for language, (directory, extension) in _LANGUAGE_DIRS.items():
        out[language] = [
            f"{RAW_BASE}/{directory}/{padded}-{slug}.{extension}",
            f"{RAW_BASE}/{directory}/{slug}.{extension}",
            f"{RAW_BASE}/{directory}/{padded}-{slug.replace('-', '_')}.{extension}",
        ]
    return out


@dataclass
class SeedReport:
    added: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    missing_reference: list[str] = field(default_factory=list)
    no_example_cases: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"added:   {len(self.added)}",
            f"skipped: {len(self.skipped)} (already present)",
            f"failed:  {len(self.failed)}",
        ]
        if self.missing_reference:
            lines.append("")
            lines.append(
                "No reference solution found — reviews for these will run "
                "without a comparison until you write one:"
            )
            lines += [f"  - {slug}" for slug in self.missing_reference]
        if self.no_example_cases:
            lines.append("")
            lines.append(
                "Stated examples could not be turned into test cases — these "
                "are tested only against oracle-derived cases, if any:"
            )
            lines += [f"  - {slug}" for slug in self.no_example_cases]
        if self.failed:
            lines.append("")
            lines.append("Failed to fetch:")
            lines += [f"  - {slug}: {error}" for slug, error in self.failed]
        return "\n".join(lines)


def fetch_reference_from_github(
    number: int, slug: str, language: str, *, client=None
) -> str | None:
    import httpx

    owns_client = client is None
    client = client or httpx.Client(timeout=15.0, follow_redirects=True)
    try:
        for url in neetcode_reference_urls(number, slug)[language]:
            try:
                response = client.get(url)
            except httpx.HTTPError:
                continue
            if response.status_code == 200 and response.text.strip():
                return response.text
        return None
    finally:
        if owns_client:
            client.close()


def _seed_one(
    slug: str,
    problem: Problem,
    fetch_reference: Callable[[int, str, str], str | None],
    root: Path | None,
    report: SeedReport,
) -> bool:
    """Seed one problem. Returns True if it landed.

    Anything that goes wrong after the directory exists rolls it back. A
    half-written directory is worse than none: `list_slugs` would report the
    problem as present, so the next run would skip it and it would never
    appear in `missing_reference` either — silently broken forever.
    """
    # Resolve the path first: save_problem writes three files in sequence,
    # and a failure after the first leaves a directory that list_slugs reads
    # as present — so the rollback has to be able to reach it even when
    # creation itself is what failed.
    directory = catalog.problem_dir(problem, root=root)

    try:
        catalog.save_problem(problem, root=root)

        got_any_reference = False
        for language, extension in LANGUAGES.items():
            source = fetch_reference(problem.number, slug, language)
            if source:
                (directory / f"reference.{extension}").write_text(source)
                got_any_reference = True

        # Example cases first: they carry LeetCode's own stated outputs, so
        # they are the only expectations that survive a missing reference —
        # and the user reading Example 1 should be tested against it.
        cases = list(problem.example_cases)

        # Oracle cases need a runnable Python reference and a seed input.
        python_reference = directory / "reference.py"
        seed_args = _seed_args_from_examples(problem)
        if python_reference.exists() and seed_args:
            cases += generate_oracle_cases(problem, python_reference, seed_args)

        if cases:
            catalog.save_tests(slug, cases, root=root)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        shutil.rmtree(directory, ignore_errors=True)
        report.failed.append((slug, f"rolled back after a partial seed: {exc}"))
        return False

    if not got_any_reference:
        report.missing_reference.append(slug)

    # Examples that exist but yielded no cases means the parse was refused.
    # Worth surfacing: silently, this is what produces a `0/0 passed` rep.
    if problem.examples and not problem.example_cases:
        report.no_example_cases.append(slug)

    report.added.append(slug)
    return True


def _seed_args_from_examples(problem: Problem) -> dict | None:
    """Parse the first example's input into an argument dict.

    Returns None when the example cannot be parsed, in which case the
    problem is seeded without oracle cases rather than with wrong ones.
    """
    import json

    if not problem.examples:
        return None

    text = problem.examples[0].input_text
    args: dict = {}
    for spec in problem.params:
        marker = f"{spec.name} = "
        if marker not in text:
            return None
        fragment = text.split(marker, 1)[1]
        # Cut at the next parameter assignment, if any. This is a textual
        # match, not a parse: a string-valued parameter whose content
        # happens to contain e.g. ", target = " would truncate early here,
        # producing invalid JSON below and discarding the example rather
        # than yielding wrong data. Not reachable by any problem in the
        # current starter set.
        for other in problem.params:
            cut = f", {other.name} = "
            if cut in fragment:
                fragment = fragment.split(cut, 1)[0]
        try:
            args[spec.name] = json.loads(fragment.strip())
        except json.JSONDecodeError:
            return None
    return args


def seed_problems(
    slugs: list[str],
    *,
    fetch: Callable[[str], Problem],
    fetch_reference: Callable[[int, str, str], str | None],
    root: Path | None = None,
) -> SeedReport:
    report = SeedReport()
    seen = set(catalog.list_slugs(root=root))

    for slug in slugs:
        if slug in seen:
            report.skipped.append(slug)
            continue
        try:
            problem = fetch(slug)
        except Exception as exc:  # noqa: BLE001 - reported, never fatal
            report.failed.append((slug, str(exc)))
            continue
        if _seed_one(slug, problem, fetch_reference, root, report):
            # Track as we go, or a slug repeated within one list is fetched
            # and written twice.
            seen.add(slug)

    return report
