"""Reading and writing problem directories.

Content lives on disk rather than in SQLite so it stays greppable,
diffable, and fixable in an editor when a fetch comes out mangled.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from algorhythm import config
from algorhythm.catalog.models import (
    LANGUAGES,
    Example,
    ParamSpec,
    Problem,
    TestCase,
)


def _root(root: Path | None) -> Path:
    return root if root is not None else config.problems_dir()


def _slug_of(directory: Path) -> str:
    """Strip the numeric prefix: `0102-level-order` -> `level-order`."""
    _, _, slug = directory.name.partition("-")
    return slug


def _problem_number(directory: Path) -> int | None:
    """The leading problem number, or None if this isn't one of our directories.

    `isdecimal()` rather than `isdigit()`: the latter is True for superscript
    and circled digits (`²`, `①`) that `int()` then rejects, which would put
    the crash back that this guard exists to prevent.
    """
    prefix, _, _ = directory.name.partition("-")
    return int(prefix) if prefix.isdecimal() else None


def _dir_for(slug: str, root: Path | None) -> Path:
    """Resolve a slug to its directory by EXACT match on the un-prefixed name.

    Suffix matching (`glob(f"*-{slug}")`) is wrong here: LeetCode has both
    `path-sum` and `binary-tree-maximum-path-sum`, and a glob for the former
    matches the latter's directory.
    """
    base = _root(root)
    matches = sorted(d for d in base.glob("*-*") if d.is_dir() and _slug_of(d) == slug)
    if not matches:
        raise FileNotFoundError(f"no problem directory for slug {slug!r} under {base}")
    if len(matches) > 1:
        names = ", ".join(d.name for d in matches)
        raise ValueError(f"ambiguous slug {slug!r}: matches {names}")
    return matches[0]


def problem_dir(problem: Problem, root: Path | None = None) -> Path:
    """Where this problem's directory belongs, whether or not it exists yet.

    Callers that need to clean up after a failed write need the path before
    the write is attempted.
    """
    return _root(root) / problem.dirname


def save_problem(problem: Problem, root: Path | None = None) -> Path:
    d = problem_dir(problem, root)
    d.mkdir(parents=True, exist_ok=True)

    meta = {
        "slug": problem.slug,
        "number": problem.number,
        "title": problem.title,
        "difficulty": problem.difficulty,
        "topics": problem.topics,
        "companies": problem.companies,
        "url": problem.url,
        "constraints": problem.constraints,
        "params": [asdict(p) for p in problem.params],
        "return_kind": problem.return_kind,
        "entry_point": problem.entry_point,
        "example_cases": [asdict(c) for c in problem.example_cases],
        "fetched_at": problem.fetched_at.isoformat(),
        "company_tags_source": problem.company_tags_source,
        "company_tags_asof": problem.company_tags_asof,
        "comparison": problem.comparison,
        "answer_param": problem.answer_param,
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    (d / "statement.md").write_text(problem.statement_md.rstrip() + "\n")
    (d / "examples.json").write_text(
        json.dumps([asdict(e) for e in problem.examples], indent=2) + "\n"
    )
    # Written verbatim, with no trailing-newline normalisation: this is the
    # exact text the solution buffer is seeded with, and LeetCode's own
    # indentation is part of the signature.
    for language, source in problem.stubs.items():
        (d / f"stub.{_ext(language)}").write_text(source)
    return d


def load_problem(slug: str, root: Path | None = None) -> Problem:
    d = _dir_for(slug, root)
    meta = json.loads((d / "meta.json").read_text())
    examples = [Example(**e) for e in json.loads((d / "examples.json").read_text())]
    return Problem(
        slug=meta["slug"],
        number=meta["number"],
        title=meta["title"],
        difficulty=meta["difficulty"],
        topics=meta["topics"],
        companies=meta["companies"],
        url=meta["url"],
        statement_md=(d / "statement.md").read_text().rstrip(),
        constraints=meta["constraints"],
        examples=examples,
        params=[ParamSpec(**p) for p in meta["params"]],
        return_kind=meta["return_kind"],
        entry_point=meta["entry_point"],
        example_cases=[TestCase(**c) for c in meta.get("example_cases", [])],
        fetched_at=datetime.fromisoformat(meta["fetched_at"]),
        company_tags_source=meta.get("company_tags_source"),
        company_tags_asof=meta.get("company_tags_asof"),
        # Absent from anything seeded before comparison modes existed.
        comparison=meta.get("comparison", "exact"),
        answer_param=meta.get("answer_param"),
        stubs=_load_stubs(d),
    )


def _load_stubs(directory: Path) -> dict[str, str]:
    """Whatever stub files are present, keyed by language.

    A problem fetched before stubs were persisted simply has none; that is a
    degraded rep, not a broken load.
    """
    stubs: dict[str, str] = {}
    for language, extension in LANGUAGES.items():
        path = directory / f"stub.{extension}"
        if path.exists():
            stubs[language] = path.read_text()
    return stubs


def list_slugs(root: Path | None = None) -> list[str]:
    """Slugs in curriculum order, i.e. by problem number.

    Sorts on the parsed integer prefix rather than the directory string, so
    ordering stays correct past four digits. Directories with a non-numeric
    prefix (a hand-made draft, or one left behind by an interrupted fetch)
    are ignored rather than crashing the listing.
    """
    base = _root(root)
    if not base.exists():
        return []

    numbered: list[tuple[int, Path]] = []
    for directory in base.iterdir():
        if not (directory.is_dir() and (directory / "meta.json").exists()):
            continue
        number = _problem_number(directory)
        if number is None:
            continue  # not a directory this module owns; ignore rather than crash
        numbered.append((number, directory))

    numbered.sort(key=lambda pair: pair[0])
    return [_slug_of(directory) for _, directory in numbered]


def save_tests(slug: str, cases: list[TestCase], root: Path | None = None) -> Path:
    d = _dir_for(slug, root)
    path = d / "tests.json"
    path.write_text(json.dumps([asdict(c) for c in cases], indent=2) + "\n")
    return path


def load_tests(slug: str, root: Path | None = None) -> list[TestCase]:
    path = _dir_for(slug, root) / "tests.json"
    if not path.exists():
        return []
    return [TestCase(**c) for c in json.loads(path.read_text())]


def _ext(language: str) -> str:
    if language not in LANGUAGES:
        raise ValueError(f"unknown language: {language}")
    return LANGUAGES[language]


def reference_path(slug: str, language: str, root: Path | None = None) -> Path:
    ext = _ext(language)
    return _dir_for(slug, root) / f"reference.{ext}"


def stub_path(slug: str, language: str, root: Path | None = None) -> Path:
    ext = _ext(language)
    return _dir_for(slug, root) / f"stub.{ext}"


# -- topics -----------------------------------------------------------------


def topics_by_slug(root: Path | None = None) -> dict[str, list[str]]:
    """Topic tags for every problem, read from meta.json alone.

    Deliberately not `load_problem`: filtering the catalog touches every
    problem in it, and the statement, examples and stubs are not needed to
    answer which topics a problem carries.
    """
    out: dict[str, list[str]] = {}
    for directory in _root(root).glob("*-*"):
        meta_path = directory / "meta.json"
        if not (directory.is_dir() and meta_path.exists()):
            continue
        if _problem_number(directory) is None:
            continue
        meta = json.loads(meta_path.read_text())
        out[_slug_of(directory)] = meta.get("topics", [])
    return out


def normalize_topic(name: str) -> str:
    """Fold a topic name to its comparison form.

    LeetCode writes `Hash Table`; a person typing it at a shell writes
    `hash-table`. Neither spelling is more correct, so both fold to the
    same thing rather than one of them being wrong.
    """
    return re.sub(r"[\s_-]+", " ", name).strip().lower()


def topic_matches(wanted: str, topic: str) -> bool:
    """Whether `wanted` names `topic`.

    Whole names only. Matching on part of one was there to forgive what
    somebody typed at a shell; topics are now chosen from a list of the
    library's own names, and partial matching against those is wrong —
    picking `Tree` would quietly also select `Binary Tree`, making the
    count shown beside it in the picker untrue.
    """
    return normalize_topic(wanted) == normalize_topic(topic)


def all_topics(root: Path | None = None) -> dict[str, int]:
    """Every topic in the library, with how many problems carry it."""
    counts: dict[str, int] = {}
    for topics in topics_by_slug(root=root).values():
        for topic in topics:
            counts[topic] = counts.get(topic, 0) + 1
    return counts


def select_by_topic(
    slugs: list[str], wanted: list[str], root: Path | None = None
) -> list[str]:
    """Those of `slugs` carrying ANY of `wanted`, in the order given.

    Any rather than all: asking for graphs and linked lists means a session
    covering both, not the handful of problems that are somehow both.
    """
    if not wanted:
        return list(slugs)
    by_slug = topics_by_slug(root=root)
    return [
        slug
        for slug in slugs
        if any(
            topic_matches(name, topic)
            for name in wanted
            for topic in by_slug.get(slug, [])
        )
    ]


