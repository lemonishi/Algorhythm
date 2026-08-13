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

from algorhythm.reviewer.prompt import RESPONSE_SCHEMA, SYSTEM_PROMPT, build_prompt
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
            "format": RESPONSE_SCHEMA,
            "options": {"temperature": 0.2},
        }

        client = self._client or httpx.Client(timeout=self._timeout_s)
        owns_client = self._client is None
        try:
            response = client.post(f"{self.host}/api/generate", json=payload)
            response.raise_for_status()
            raw_body = response.text
        except httpx.HTTPError as exc:
            raise ReviewerUnavailable(
                f"Ollama at {self.host} could not be reached or returned an "
                f"error: {exc}. Start it with `ollama serve`, or grade this "
                "rep yourself."
            ) from exc
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
