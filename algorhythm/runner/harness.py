"""Result types shared by both language runners."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CaseStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class CaseResult:
    id: str
    status: CaseStatus
    expected: Any = None
    actual: Any = None
    error: str | None = None
    duration_ms: int = 0


@dataclass(frozen=True)
class RunResult:
    cases: list[CaseResult] = field(default_factory=list)
    compile_error: str | None = None

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.status is CaseStatus.PASS)

    @property
    def ok(self) -> bool:
        return self.compile_error is None and self.passed == self.total

    @property
    def summary(self) -> str:
        if self.compile_error:
            return "compile error"
        return f"{self.passed}/{self.total} passed"
