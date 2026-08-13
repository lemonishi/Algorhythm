import json

import httpx
import pytest

from algorhythm.reviewer.ollama import OllamaReviewer
from algorhythm.reviewer.protocol import Review, ReviewerUnavailable
from algorhythm.scheduler.sm2 import Grade
from tests.reviewer.test_prompt import request


def transport(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def ok_response(payload: dict):
    def handler(_request):
        return httpx.Response(200, json={"response": json.dumps(payload)})

    return handler


def test_parses_a_well_formed_response():
    client = transport(
        ok_response(
            {
                "review": "You used sorting; the intended approach is a hash map.",
                "proposed_grade": "hard",
                "grade_reason": "Correct but not the intended pattern.",
            }
        )
    )
    review = OllamaReviewer(client=client).review(request())
    assert isinstance(review, Review)
    assert review.proposed_grade is Grade.HARD
    assert "hash map" in review.text
    assert review.grade_reason.startswith("Correct")


def test_records_the_model_name():
    client = transport(ok_response({"review": "x", "proposed_grade": "good"}))
    review = OllamaReviewer(model="qwen2.5-coder:7b", client=client).review(request())
    assert review.model == "qwen2.5-coder:7b"


def test_sends_the_configured_model_and_a_json_schema():
    captured = {}

    def handler(req):
        captured.update(json.loads(req.content))
        return httpx.Response(200, json={"response": json.dumps({"review": "x"})})

    OllamaReviewer(model="custom:1b", client=transport(handler)).review(request())
    assert captured["model"] == "custom:1b"
    assert captured["stream"] is False
    assert captured["format"]["type"] == "object"


def test_connection_failure_raises_reviewer_unavailable():
    def handler(_request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ReviewerUnavailable, match="Ollama"):
        OllamaReviewer(client=transport(handler)).review(request())


def test_http_error_raises_reviewer_unavailable():
    def handler(_request):
        return httpx.Response(500, text="internal error")

    with pytest.raises(ReviewerUnavailable):
        OllamaReviewer(client=transport(handler)).review(request())


def test_non_json_body_is_returned_as_raw_text_without_a_grade():
    """Nothing may block the loop — a malformed review still shows, the
    user just grades it themselves."""

    def handler(_request):
        return httpx.Response(200, json={"response": "I think it looks fine!"})

    review = OllamaReviewer(client=transport(handler)).review(request())
    assert review.proposed_grade is None
    assert "looks fine" in review.text


def test_unrecognised_grade_is_discarded_but_text_is_kept():
    client = transport(
        ok_response({"review": "solid", "proposed_grade": "excellent"})
    )
    review = OllamaReviewer(client=client).review(request())
    assert review.proposed_grade is None
    assert review.text == "solid"


def test_missing_review_field_falls_back_to_the_raw_body():
    client = transport(ok_response({"proposed_grade": "good"}))
    review = OllamaReviewer(client=client).review(request())
    assert review.proposed_grade is Grade.GOOD
    assert review.text != ""


def test_non_json_top_level_body_degrades_rather_than_raising():
    """A reachable-but-malformed Ollama (proxy, truncated stream) must not
    crash the caller with a JSONDecodeError it has no reason to catch."""

    def handler(_request):
        return httpx.Response(200, text="<html>502 Bad Gateway</html>")

    review = OllamaReviewer(client=transport(handler)).review(request())
    assert isinstance(review, Review)
    assert "502 Bad Gateway" in review.text
    assert review.proposed_grade is None


def test_non_object_top_level_json_degrades_rather_than_raising():
    """A JSON array or scalar at the top level must not crash the caller
    with an AttributeError from calling .get() on it."""

    def handler(_request):
        return httpx.Response(200, json=["unexpected"])

    review = OllamaReviewer(client=transport(handler)).review(request())
    assert isinstance(review, Review)
    assert review.proposed_grade is None


def test_empty_body_degrades_rather_than_raising():
    def handler(_request):
        return httpx.Response(200, text="")

    review = OllamaReviewer(client=transport(handler)).review(request())
    assert isinstance(review, Review)
    assert review.proposed_grade is None
