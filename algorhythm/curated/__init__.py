"""Hand-maintained corrections layered over what seeding fetches.

Seeding takes statements from LeetCode and reference solutions from
neetcode-gh, and there are three things neither source can give us:

  * a reference that does not parse — upstream ships one with broken
    indentation, and a reference that will not load means no oracle cases
    and nothing for the reviewer to compare against;
  * test cases JSON cannot express, such as a linked list with a cycle,
    where LeetCode states the back-edge out of band as `pos = 1`;
  * "in any order", which LeetCode says in prose in the statement and
    nowhere in the API, but which decides whether a correct answer passes.

Everything here is keyed by slug and every part is optional: a problem with
no directory seeds exactly as it did before. Each directory may hold
`reference.py`, `reference.cpp`, `tests.json`, and `problem.json`.
"""

from __future__ import annotations

import json
from pathlib import Path

from algorhythm.catalog.models import LANGUAGES, TestCase

ROOT = Path(__file__).parent


def _read(slug: str, name: str) -> str | None:
    path = ROOT / slug / name
    return path.read_text() if path.exists() else None


def reference(slug: str, language: str) -> str | None:
    """A curated reference solution, preferred over the fetched one."""
    return _read(slug, f"reference.{LANGUAGES[language]}")


def tests(slug: str) -> list[TestCase] | None:
    """Curated cases, used INSTEAD of generated ones.

    Instead of, not alongside: a curated set exists precisely because the
    generated ones are wrong or absent, and mixing the two would reintroduce
    whatever was wrong with them.
    """
    raw = _read(slug, "tests.json")
    return [TestCase(**case) for case in json.loads(raw)] if raw else None


def overrides(slug: str) -> dict:
    """Problem fields to override, e.g. `{"comparison": "unordered"}`."""
    raw = _read(slug, "problem.json")
    return json.loads(raw) if raw else {}
