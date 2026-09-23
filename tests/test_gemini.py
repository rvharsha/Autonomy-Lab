"""Mock-transport protocol checks only; these are not model evaluation evidence."""

import copy
import json
import traceback

import httpx
import pytest

from autonomy_lab.gemini import GeminiClient, GeminiError

CONTENTS = [{"role": "user", "parts": [{"text": "Inspect the service."}]}]
DECLARATIONS = [{"name": "inspect_service", "parameters": {"type": "OBJECT", "properties": {}}}]


def provider_response():
    return {
        "candidates": [{
            "content": {
                "role": "model",
                "parts": [{
                    "functionCall": {"name": "inspect_service", "args": {}, "id": "unit-call"},
                    "thoughtSignature": "unit-test-opaque-signature",
                }],
            },
            "finishReason": "STOP",
        }],
        "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 3, "totalTokenCount": 19, "thoughtsTokenCount": 4},
        "modelVersion": "gemini-3.8-flash",
        "responseId": "unit-test-response",
    }


def test_exact_request_and_lossless_response():
    expected = provider_response()
    observed = []

    def respond(request):
        observed.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
        assert request.headers["x-goog-api-key"] == "unit-test-key"
        assert request.extensions["timeout"] == {"connect": 7.0, "read": 7.0, "write": 7.0, "pool": 7.0}
        assert json.loads(request.content) == {
            "contents": CONTENTS,
            "systemInstruction": {"parts": [{"text": "Use the permitted tools."}]},
            "tools": [{"functionDeclarations": DECLARATIONS}],
            "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
            "generationConfig": {"temperature": 1, "maxOutputTokens": 1024, "candidateCount": 1},
        }
        return httpx.Response(200, json=expected)

    original_contents = copy.deepcopy(CONTENTS)
    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        client = GeminiClient("unit-test-key", timeout=7, client=http_client)
        result = client.generate(CONTENTS, "Use the permitted tools.", DECLARATIONS, 1024)
        assert not http_client.is_closed
    assert result == expected
    assert len(observed) == 1
    assert CONTENTS == original_contents


def test_preserves_previous_model_content_and_empty_tools():
    contents = CONTENTS + [provider_response()["candidates"][0]["content"]]

    def respond(request):
        body = json.loads(request.content)
        assert body["contents"] == contents
        assert "tools" not in body
        assert "toolConfig" not in body
        return httpx.Response(200, json=provider_response())

    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        GeminiClient("unit-test-key", client=transport).generate(contents, "System", [])


@pytest.mark.parametrize("source", ["GEMINI_API_KEY", "GOOGLE_API_KEY"])
def test_environment_key(monkeypatch, source):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv(source, "unit-env-key")

    def respond(request):
        assert request.headers["x-goog-api-key"] == "unit-env-key"
        return httpx.Response(200, json=provider_response())

    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        GeminiClient(client=transport).generate(CONTENTS, "System", [])


def test_explicit_key_takes_precedence(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "unit-env-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "unit-other-key")

    def respond(request):
        assert request.headers["x-goog-api-key"] == "unit-explicit-key"
        return httpx.Response(200, json=provider_response())

    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        GeminiClient("unit-explicit-key", client=transport).generate(CONTENTS, "System", [])


def test_missing_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(GeminiError, match="Set GEMINI_API_KEY or GOOGLE_API_KEY"):
        GeminiClient()


@pytest.mark.parametrize("key", ["", " ", "invalid\nkey", "non-ascii-\u2603"])
def test_invalid_key_is_not_echoed(key):
    with pytest.raises(GeminiError) as raised:
        GeminiClient(key)
    assert "invalid\nkey" not in str(raised.value)
    assert "non-ascii" not in str(raised.value)


@pytest.mark.parametrize("model", ["https://example.com", "gemini-3.8-flash?key=secret", "gemini-../other", "models/gemini-3.8-flash", "gemini-\n"])
def test_model_must_be_bare_identifier(model):
    with pytest.raises(ValueError, match="model ID"):
        GeminiClient("unit-test-key", model=model)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), None, True])
def test_timeout_must_be_finite_positive(timeout):
    with pytest.raises(ValueError, match="finite positive"):
        GeminiClient("unit-test-key", timeout=timeout)


@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 429, 500, 503])
def test_http_errors_are_sanitized_and_not_retried(status):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, headers={"location": "https://example.com/stolen"}, json={"error": {"message": "unit-private-secret"}})

    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True) as transport:
        with pytest.raises(GeminiError, match=f"HTTP {status}") as raised:
            GeminiClient("unit-private-secret", client=transport).generate(CONTENTS, "System", [])
    assert len(calls) == 1
    assert raised.value.status_code == status
    assert raised.value.response is None
    assert "unit-private-secret" not in str(raised.value)


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
def test_transport_errors_are_sanitized_and_not_retried(error):
    calls = []

    def fail(request):
        calls.append(request)
        raise error("unit-private-secret", request=request)

    with httpx.Client(transport=httpx.MockTransport(fail)) as transport:
        with pytest.raises(GeminiError, match="No retry was attempted") as raised:
            GeminiClient("unit-private-secret", client=transport).generate(CONTENTS, "System", [])
    assert len(calls) == 1
    rendered = "".join(traceback.format_exception_only(raised.type, raised.value))
    assert "unit-private-secret" not in rendered
    assert raised.value.__suppress_context__


@pytest.mark.parametrize("reason", ["MAX_TOKENS", "SAFETY", "MALFORMED_FUNCTION_CALL", "unit-private-secret", None])
def test_incomplete_generation_preserves_usage_without_executing(reason):
    data = provider_response()
    data["candidates"][0]["finishReason"] = reason
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data))) as transport:
        with pytest.raises(GeminiError, match="incomplete") as raised:
            GeminiClient("unit-test-key", client=transport).generate(CONTENTS, "System", DECLARATIONS)
    assert raised.value.response == data
    assert "unit-private-secret" not in str(raised.value)


@pytest.mark.parametrize("data", [
    {}, {"candidates": []}, {"candidates": [None]},
    {"candidates": [{"finishReason": "STOP"}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": []}}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{}]}}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": ["text"]}}]},
    {"promptFeedback": {"blockReason": "SAFETY"}, "usageMetadata": {"promptTokenCount": 4}},
])
def test_unusable_generation_fails_with_original_evidence(data):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data))) as transport:
        with pytest.raises(GeminiError) as raised:
            GeminiClient("unit-test-key", client=transport).generate(CONTENTS, "System", [])
    assert raised.value.response == data


@pytest.mark.parametrize("body", [b"not-json-unit-private-secret", b"[]", b"null"])
def test_bad_response_json(body):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))) as transport:
        with pytest.raises(GeminiError) as raised:
            GeminiClient("unit-test-key", client=transport).generate(CONTENTS, "System", [])
    assert "unit-private-secret" not in str(raised.value)


@pytest.mark.parametrize("budget", [0, -1, 65537, True, 1.5])
def test_invalid_output_token_budget_fails_before_network(budget):
    def unexpected(request):
        pytest.fail("invalid token budget must not issue a billable request")

    with httpx.Client(transport=httpx.MockTransport(unexpected)) as transport:
        with pytest.raises(ValueError, match="max_output_tokens"):
            GeminiClient("unit-test-key", client=transport).generate(CONTENTS, "System", [], budget)


def test_count_tokens_sends_full_generation_input_and_preserves_signatures():
    contents = CONTENTS + [provider_response()["candidates"][0]["content"]]
    original = copy.deepcopy(contents)
    requests = []

    def respond(request):
        requests.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:countTokens"
        assert request.headers["x-goog-api-key"] == "unit-count-key"
        assert request.extensions["timeout"]["read"] == 9.0
        assert json.loads(request.content) == {
            "generateContentRequest": {
                "model": "models/gemini-3.8-flash",
                "contents": contents,
                "systemInstruction": {"parts": [{"text": "System instruction is counted."}]},
                "tools": [{"functionDeclarations": DECLARATIONS}],
                "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
                "generationConfig": {"temperature": 1, "candidateCount": 1},
            }
        }
        return httpx.Response(200, json={"totalTokens": 1234})

    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        result = GeminiClient("unit-count-key", timeout=9, client=transport).count_tokens(contents, "System instruction is counted.", DECLARATIONS)
    assert result == 1234
    assert len(requests) == 1
    assert contents == original


def test_count_and_generation_use_identical_input_fields():
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"totalTokens": 19} if len(requests) == 1 else provider_response())

    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        client = GeminiClient("unit-test-key", client=transport)
        assert client.count_tokens(CONTENTS, "System", DECLARATIONS) == 19
        client.generate(CONTENTS, "System", DECLARATIONS, max_output_tokens=100)
    counted = requests[0]["generateContentRequest"]
    counted.pop("model")
    requests[1]["generationConfig"].pop("maxOutputTokens")
    assert counted == requests[1]


@pytest.mark.parametrize("data", [{}, {"totalTokens": -1}, {"totalTokens": True}, {"totalTokens": "12"}, {"totalTokens": 1.5}, []])
def test_count_tokens_rejects_unknown_or_invalid_counts(data):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data))) as transport:
        with pytest.raises(GeminiError):
            GeminiClient("unit-test-key", client=transport).count_tokens(CONTENTS, "System", [])


@pytest.mark.parametrize("status", [302, 401, 429, 500])
def test_count_tokens_http_failure_never_retries_redirects_or_exposes_secrets(status):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, headers={"location": "https://unit.invalid/leak"}, json={"error": {"message": "unit-private-key"}})

    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True) as transport:
        with pytest.raises(GeminiError) as raised:
            GeminiClient("unit-private-key", client=transport).count_tokens(CONTENTS, "System", [])
    assert len(requests) == 1
    assert raised.value.status_code == status
    assert "unit-private-key" not in str(raised.value)
    assert raised.value.response is None


def test_count_tokens_timeout_is_sanitized_and_not_retried():
    requests = []

    def fail(request):
        requests.append(request)
        raise httpx.ReadTimeout("unit-private-key", request=request)

    with httpx.Client(transport=httpx.MockTransport(fail)) as transport:
        with pytest.raises(GeminiError, match="countTokens request timed out") as raised:
            GeminiClient("unit-private-key", client=transport).count_tokens(CONTENTS, "System", [])
    assert len(requests) == 1
    assert "unit-private-key" not in str(raised.value)
