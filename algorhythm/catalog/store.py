"""Reading and writing problem directories.

Content lives on disk rather than in SQLite so it stays greppable,
diffable, and fixable in an editor when a fetch comes out mangled.
"""

from __future__ import annotations

import json
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


def _dir_for(slug: str, root: Path | None) -> Path:
    base = _root(root)
    matches = sorted(base.glob(f"*-{slug}"))
    if not matches:
        raise FileNotFoundError(f"no problem directory for slug {slug!r} under {base}")
    return matches[0]


def save_problem(problem: Problem, root: Path | None = None) -> Path:
    d = _root(root) / problem.dirname
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
        "fetched_at": problem.fetched_at.isoformat(),
        "company_tags_source": problem.company_tags_source,
        "company_tags_asof": problem.company_tags_asof,
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    (d / "statement.md").write_text(problem.statement_md.rstrip() + "\n")
    (d / "examples.json").write_text(
        json.dumps([asdict(e) for e in problem.examples], indent=2) + "\n"
    )
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
        fetched_at=datetime.fromisoformat(meta["fetched_at"]),
        company_tags_source=meta.get("company_tags_source"),
        company_tags_asof=meta.get("company_tags_asof"),
    )


def list_slugs(root: Path | None = None) -> list[str]:
    """Slugs in curriculum order — which is problem-number order, because
    the directory name is number-prefixed."""
    base = _root(root)
    if not base.exists():
        return []
    out = []
    for d in sorted(base.iterdir()):
        if d.is_dir() and (d / "meta.json").exists():
            out.append(json.loads((d / "meta.json").read_text())["slug"])
    return out


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
