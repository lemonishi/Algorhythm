"""Ollama-backed reviewer.

One HTTP POST. Ollama's `format` parameter takes a JSON schema, so the
response arrives structured and no output-parsing layer is needed.

Every parse failure degrades rather than raises: a malformed review is
still shown, the user just grades it themselves. Only an unreachable
service raises, and callers catch that to skip review entirely.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace

import httpx

from algorhythm.reviewer.prompt import RESPONSE_SCHEMA, SYSTEM_PROMPT, build_prompt
from algorhythm.reviewer.protocol import Review, ReviewerUnavailable, ReviewRequest
from algorhythm.scheduler.sm2 import Grade

DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_HOST = "http://localhost:11434"
# Generous, because this is local generation on whatever machine you have.
# A 7B model on a memory-constrained laptop was measured at 468s for one
# review; at the old 120s every review failed, and a timeout reads as a
# broken reviewer rather than as a model too large for the machine.
DEFAULT_TIMEOUT_S = 600.0


def _configured_timeout() -> float:
    """`ALGORHYTHM_REVIEW_TIMEOUT` in seconds, or the default.

    A bad value falls back rather than raising: spec 11 says nothing blocks
    the loop, and a typo in an environment variable is no reason to lose a
    finished rep.
    """
    raw = os.environ.get("ALGORHYTHM_REVIEW_TIMEOUT")
    if not raw:
        return DEFAULT_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_S
    return value if value > 0 else DEFAULT_TIMEOUT_S


class OllamaReviewer:
    def __init__(
        self,
        model: str | None = None,
        host: str | None = None,
        client: httpx.Client | None = None,
        timeout_s: float | None = None,
    ) -> None:
        """Model, host and timeout come from the environment when not given.

        The model matters most: how big a model this machine can run is a
        property of the machine, not of the code, and the only remedy for a
        machine that cannot spare the memory is a smaller one. Editing the
        source to change it is not a remedy anybody reaches for.
        """
        self.model = model or os.environ.get("ALGORHYTHM_MODEL") or DEFAULT_MODEL
        self.host = (
            host or os.environ.get("ALGORHYTHM_OLLAMA_HOST") or DEFAULT_HOST
        ).rstrip("/")
        self._client = client
        self._timeout_s = (
            timeout_s if timeout_s is not None else _configured_timeout()
        )

    def review(self, request: ReviewRequest) -> Review:
        payload = {
            "model": self.model,
            "system": SYSTEM_PROMPT,
            "prompt": build_prompt(request),
            "stream": False,
            "format": RESPONSE_SCHEMA,
            "options": {"temperature": 0.2},
        }

        # Only when asked. Ollama's own default keeps the model resident for
        # five minutes, which is right on a machine with memory to spare and
        # five minutes of swapping on one without.
        keep_alive = os.environ.get("ALGORHYTHM_OLLAMA_KEEP_ALIVE")
        if keep_alive:
            payload["keep_alive"] = keep_alive

        client = self._client or httpx.Client(timeout=self._timeout_s)
        owns_client = self._client is None
        try:
            response = client.post(f"{self.host}/api/generate", json=payload)
            response.raise_for_status()
            raw_body = response.text
        except httpx.HTTPError as exc:
            raise ReviewerUnavailable(self._unavailable_reason(exc)) from exc
        finally:
            if owns_client:
                client.close()

        # Reachable but malformed. Degrade rather than raise: only an
        # unreachable service may stop a rep, and a JSONDecodeError or an
        # AttributeError escaping here would crash a caller that has no
        # reason to catch either.
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            return Review(text=raw_body.strip(), model=self.model)

        if not isinstance(body, dict):
            return Review(text=raw_body.strip(), model=self.model)

        return self._graded_by_tests(
            self._to_review(body.get("response", "")), request.run_result
        )

    @staticmethod
    def _graded_by_tests(review: Review, run_result) -> Review:
        """Hold the proposed grade to what the tests actually showed.

        The system prompt already says the tests are authoritative for
        correctness, and models still ignore it: one proposing `hard` for a
        solution that failed every case was measured. A grade is the input
        to the scheduler, so an inflated one on a solution that does not
        work brings the problem back too late.

        Only the unambiguous case. Some tests passing is a judgement call,
        which is the whole reason there is a model here.
        """
        nothing_worked = run_result.compile_error is not None or (
            run_result.total > 0 and run_result.passed == 0
        )
        if nothing_worked and review.proposed_grade is not Grade.AGAIN:
            return replace(review, proposed_grade=Grade.AGAIN)
        return review

    def _unavailable_reason(self, exc: httpx.HTTPError) -> str:
        """Say which of the two first-run failures this is.

        A running server that has never been told to fetch the model is the
        likeliest one, and Ollama reports it as a plain 404. Folding it in
        with a refused connection sends the reader off to restart a daemon
        that is working fine.
        """
        if (
            isinstance(exc, httpx.HTTPStatusError)
            and exc.response.status_code == 404
        ):
            return (
                f"Ollama at {self.host} has no model named {self.model!r}. "
                f"Fetch it with `ollama pull {self.model}`, or grade this "
                "rep yourself."
            )
        return (
            f"Ollama at {self.host} could not be reached or returned an "
            f"error: {exc}. Start it with `ollama serve`, or grade this "
            "rep yourself."
        )

    def _to_review(self, raw: str) -> Review:
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            return Review(text=raw.strip(), model=self.model)

        try:
            grade = Grade(parsed.get("proposed_grade"))
        except ValueError:
            grade = None

        return Review(
            text=str(parsed.get("review") or raw).strip(),
            proposed_grade=grade,
            grade_reason=parsed.get("grade_reason"),
            model=self.model,
        )
