"""Ollama-backed reviewer.

One HTTP POST. Ollama's `format` parameter takes a JSON schema, so the
response arrives structured and no output-parsing layer is needed.

Every parse failure degrades rather than raises: a malformed review is
still shown, the user just grades it themselves. Only an unreachable
service raises, and callers catch that to skip review entirely.
"""

from __future__ import annotations

import json

import httpx

from algorhythm.reviewer.prompt import (
    SYSTEM_PROMPT,
    build_prompt,
    response_schema,
)
from algorhythm.reviewer.protocol import Review, ReviewerUnavailable, ReviewRequest
from algorhythm.scheduler.sm2 import Grade

DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_HOST = "http://localhost:11434"


class OllamaReviewer:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        host: str = DEFAULT_HOST,
        client: httpx.Client | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self._client = client
        self._timeout_s = timeout_s

    def review(self, request: ReviewRequest) -> Review:
        payload = {
            "model": self.model,
            "system": SYSTEM_PROMPT,
            "prompt": build_prompt(request),
            "stream": False,
            "format": response_schema(request),
            "options": {"temperature": 0.2},
        }

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

        return self._to_review(body.get("response", ""))

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

        # `or None` rather than the raw value: a model asked for an
        # optional string tends to answer "" instead of omitting the key,
        # and an empty heading in the review pane is worse than no heading.
        since_last = str(parsed.get("since_last") or "").strip() or None

        return Review(
            text=str(parsed.get("review") or raw).strip(),
            proposed_grade=grade,
            grade_reason=parsed.get("grade_reason"),
            since_last=since_last,
            model=self.model,
        )
