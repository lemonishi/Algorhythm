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


def test_connection_failure_says_to_start_the_server():
    def handler(_request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ReviewerUnavailable) as caught:
        OllamaReviewer(client=transport(handler)).review(request())
    assert "ollama serve" in str(caught.value)


def test_a_missing_model_says_to_pull_it_and_names_it():
    """Ollama answers 404 for a model it does not have.

    A reachable server with the model absent is the likeliest first-run
    failure, and the fix is `ollama pull` — not `ollama serve`. Reporting
    it as an unreachable server sends the reader to restart a daemon that
    is already running fine.
    """

    def handler(_request):
        return httpx.Response(404, json={"error": "model 'absent:7b' not found"})

    with pytest.raises(ReviewerUnavailable) as caught:
        OllamaReviewer(model="absent:7b", client=transport(handler)).review(request())

    message = str(caught.value)
    assert "ollama pull absent:7b" in message
    assert "ollama serve" not in message


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


def test_a_since_last_note_is_parsed_off_the_response():
    client = transport(
        ok_response(
            {
                "review": "Hash map, matches the reference.",
                "proposed_grade": "good",
                "since_last": "You replaced the nested loop with a hash map.",
            }
        )
    )
    review = OllamaReviewer(client=client).review(request())
    assert review.since_last == "You replaced the nested loop with a hash map."


def test_a_missing_since_last_is_simply_absent():
    client = transport(ok_response({"review": "x", "proposed_grade": "good"}))
    assert OllamaReviewer(client=client).review(request()).since_last is None


def test_an_empty_since_last_is_treated_as_absent():
    """Models emit "" for an optional string rather than omitting it, and an
    empty heading in the review pane is worse than no heading."""
    client = transport(
        ok_response({"review": "x", "proposed_grade": "good", "since_last": "  "})
    )
    assert OllamaReviewer(client=client).review(request()).since_last is None


# -- configuration ----------------------------------------------------------


def test_the_model_can_be_chosen_by_environment(monkeypatch):
    """A 7B model needs ~5GB resident. On a machine that cannot spare it the
    reviewer is unusably slow, and the only fix is a smaller model — so
    picking one must not require editing the source."""
    monkeypatch.setenv("ALGORHYTHM_MODEL", "qwen2.5-coder:3b")
    assert OllamaReviewer().model == "qwen2.5-coder:3b"


def test_an_explicit_model_beats_the_environment(monkeypatch):
    monkeypatch.setenv("ALGORHYTHM_MODEL", "from-env")
    assert OllamaReviewer(model="explicit").model == "explicit"


def test_the_default_model_is_used_without_configuration(monkeypatch):
    monkeypatch.delenv("ALGORHYTHM_MODEL", raising=False)
    assert OllamaReviewer().model == "qwen2.5-coder:7b"


def test_the_timeout_can_be_raised_by_environment(monkeypatch):
    """Local generation is slow on a memory-constrained machine — measured
    at 468s for one review on an 8GB M2. A fixed 120s makes every review
    fail there, and the failure looks like a broken reviewer."""
    monkeypatch.setenv("ALGORHYTHM_REVIEW_TIMEOUT", "900")
    assert OllamaReviewer()._timeout_s == 900.0


def test_a_nonsense_timeout_falls_back_to_the_default(monkeypatch):
    """A bad value must not stop the rep — spec 11: nothing blocks the loop."""
    monkeypatch.setenv("ALGORHYTHM_REVIEW_TIMEOUT", "soon")
    assert OllamaReviewer()._timeout_s == 600.0


def test_the_host_can_be_pointed_elsewhere(monkeypatch):
    monkeypatch.setenv("ALGORHYTHM_OLLAMA_HOST", "http://box:11434")
    assert OllamaReviewer().host == "http://box:11434"


def test_how_long_the_model_stays_resident_is_configurable(monkeypatch):
    """Ollama keeps a model loaded for five minutes after a request.

    On a machine with little memory to spare that is five minutes of the
    whole laptop swapping after a review that already finished — so how
    long it lingers has to be something you can turn down.
    """
    monkeypatch.setenv("ALGORHYTHM_OLLAMA_KEEP_ALIVE", "30s")
    captured = {}

    def handler(req):
        captured.update(json.loads(req.content))
        return httpx.Response(200, json={"response": json.dumps({"review": "x"})})

    OllamaReviewer(client=transport(handler)).review(request())
    assert captured["keep_alive"] == "30s"


def test_residency_is_left_to_ollama_when_unset(monkeypatch):
    """No opinion by default: unloading between reps costs a reload, which
    is the wrong trade on a machine that has the memory."""
    monkeypatch.delenv("ALGORHYTHM_OLLAMA_KEEP_ALIVE", raising=False)
    captured = {}

    def handler(req):
        captured.update(json.loads(req.content))
        return httpx.Response(200, json={"response": json.dumps({"review": "x"})})

    OllamaReviewer(client=transport(handler)).review(request())
    assert "keep_alive" not in captured


# -- the tests are authoritative for correctness ----------------------------


def failing(total=5):
    from algorhythm.runner.harness import CaseResult, CaseStatus, RunResult

    return RunResult(
        cases=[
            CaseResult(id=f"c{i}", status=CaseStatus.FAIL) for i in range(total)
        ]
    )


def test_a_solution_that_passes_nothing_is_proposed_as_again():
    """Measured: a solution returning [0, 0] failed every test and the model
    proposed `hard`. The system prompt already says the tests are
    authoritative for correctness — so they decide this, not the model.
    """
    client = transport(ok_response({"review": "wrong", "proposed_grade": "hard"}))
    review = OllamaReviewer(client=client).review(
        request(run_result=failing())
    )
    assert review.proposed_grade is Grade.AGAIN


def test_a_solution_that_does_not_compile_is_proposed_as_again():
    from algorhythm.runner.harness import RunResult

    client = transport(ok_response({"review": "x", "proposed_grade": "good"}))
    review = OllamaReviewer(client=client).review(
        request(run_result=RunResult(compile_error="SyntaxError"))
    )
    assert review.proposed_grade is Grade.AGAIN


def test_a_partly_passing_solution_keeps_the_models_grade():
    """Only the unambiguous case is overridden. Some tests passing is a
    judgement call, which is what the model is for."""
    from algorhythm.runner.harness import CaseResult, CaseStatus, RunResult

    partly = RunResult(
        cases=[
            CaseResult(id="a", status=CaseStatus.PASS),
            CaseResult(id="b", status=CaseStatus.FAIL),
        ]
    )
    client = transport(ok_response({"review": "x", "proposed_grade": "hard"}))
    assert (
        OllamaReviewer(client=client).review(request(run_result=partly)).proposed_grade
        is Grade.HARD
    )


def test_no_tests_at_all_leaves_the_grade_alone():
    """`0/0` is a problem with no cases, not a failed solution."""
    from algorhythm.runner.harness import RunResult

    client = transport(ok_response({"review": "x", "proposed_grade": "good"}))
    review = OllamaReviewer(client=client).review(
        request(run_result=RunResult(cases=[]))
    )
    assert review.proposed_grade is Grade.GOOD
