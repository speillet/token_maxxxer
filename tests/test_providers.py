import json

import httpx
import pytest
from pydantic import SecretStr

from token_maxxxer.config import ProviderConfig
from token_maxxxer.providers import GenerationRequest, UnsupportedProviderError, create_provider

KEY = "sk-fixture-api-key"


def payload(name: str) -> dict:
    if name == "claude":
        return {
            "id": "msg_fixture",
            "type": "message",
            "role": "assistant",
            "model": "fixture-model",
            "content": [{"type": "text", "text": "Done."}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 12, "output_tokens": 7},
        }
    return {
        "id": "resp_fixture",
        "object": "response",
        "created_at": 0,
        "model": "fixture-model",
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "output": [
            {
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "Done.", "annotations": []}],
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "none",
        "tools": [],
        "usage": {
            "input_tokens": 12,
            "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
            "output_tokens": 7,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 19,
        },
    }


def generate(name, handler):
    settings = ProviderConfig(name=name, model="fixture-model", max_output_tokens=128)
    provider = create_provider(settings, transport=httpx.MockTransport(handler))
    return provider.generate(
        GenerationRequest(prompt="Consigne explicite.", settings=settings), SecretStr(KEY)
    )


@pytest.mark.parametrize("name", ["claude", "openai"])
def test_provider_request_and_usage(name, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://untrusted.example")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://untrusted.example")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "fixture-oauth-not-used")
    calls = []

    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body["model"] == "fixture-model"
        if name == "claude":
            assert str(request.url) == "https://api.anthropic.com/v1/messages"
            assert request.headers["x-api-key"] == KEY
            assert "authorization" not in request.headers
            assert body["max_tokens"] == 128
            assert body["messages"][0]["content"] == "Consigne explicite."
        else:
            assert str(request.url) == "https://api.openai.com/v1/responses"
            assert request.headers["authorization"] == "Bearer " + KEY
            assert body["max_output_tokens"] == 128
            assert body["store"] is False
            assert body["input"] == "Consigne explicite."
        return httpx.Response(200, json=payload(name))

    result = generate(name, handler)
    assert result.status == "success"
    assert result.text == "Done."
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 7
    assert result.usage.estimated_cost_usd is None
    assert result.stdout == result.stderr == ""
    assert len(calls) == 1
    assert KEY not in result.model_dump_json()


@pytest.mark.parametrize("name", ["claude", "openai"])
@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (401, "auth_error"),
        (403, "auth_error"),
        (429, "rate_limited"),
        (408, "transient_error"),
        (500, "transient_error"),
        (529, "transient_error"),
        (400, "invalid_output"),
        (307, "invalid_output"),
    ],
)
def test_http_errors_are_classified_without_retries_or_error_body(name, code, expected) -> None:
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            code,
            json={"error": {"type": "fixture", "message": KEY}},
            headers={"location": "https://untrusted.example", "retry-after": "0"},
        )

    result = generate(name, handler)
    assert result.status == expected
    assert KEY not in result.model_dump_json()
    assert len(calls) == 1


@pytest.mark.parametrize("name", ["claude", "openai"])
@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        (httpx.ReadTimeout, "timeout"),
        (httpx.ConnectError, "transient_error"),
    ],
)
def test_network_errors_are_not_retried(name, error_type, expected) -> None:
    calls = []

    def handler(request):
        calls.append(request)
        raise error_type(KEY, request=request)

    result = generate(name, handler)
    assert result.status == expected
    assert len(calls) == 1
    assert KEY not in result.model_dump_json()


@pytest.mark.parametrize("name", ["claude", "openai"])
def test_malformed_responses_do_not_count_as_success(name) -> None:
    assert (
        generate(name, lambda _: httpx.Response(200, json={"unexpected": KEY})).status
        == "invalid_output"
    )


@pytest.mark.parametrize("name", ["claude", "openai"])
def test_incomplete_generation_is_not_success(name) -> None:
    data = payload(name)
    if name == "claude":
        data["stop_reason"] = "max_tokens"
    else:
        data["status"] = "incomplete"
        data["incomplete_details"] = {"reason": "max_output_tokens"}
    assert generate(name, lambda _: httpx.Response(200, json=data)).status == "invalid_output"


def test_unknown_openai_usage_remains_unknown() -> None:
    data = payload("openai")
    data["usage"] = None
    result = generate("openai", lambda _: httpx.Response(200, json=data))
    assert result.status == "success" and result.usage is None


def test_copilot_does_not_claim_implementation() -> None:
    with pytest.raises(UnsupportedProviderError, match="SDK officiel"):
        create_provider(ProviderConfig(name="copilot", model="fixture-model"))


@pytest.mark.parametrize("case", ["refusal", "incomplete", "in_progress", "tool", "reasoning"])
def test_openai_output_items_must_also_be_complete(case) -> None:
    data = payload("openai")
    if case == "refusal":
        data["output"][0]["content"].append({"type": "refusal", "refusal": "Cannot comply."})
    elif case in ("incomplete", "in_progress"):
        data["output"][0]["status"] = case
    elif case == "tool":
        data["output"].append(
            {
                "id": "fc_fixture",
                "type": "function_call",
                "call_id": "call_fixture",
                "name": "unapproved",
                "arguments": "{}",
                "status": "completed",
            }
        )
    else:
        data["output"].append(
            {"id": "reasoning_fixture", "type": "reasoning", "summary": [], "status": "incomplete"}
        )
    result = generate("openai", lambda _: httpx.Response(200, json=data))
    assert result.status == "invalid_output"


def test_claude_does_not_treat_an_unhandled_tool_call_as_completed_text() -> None:
    data = payload("claude")
    data["content"].append(
        {"type": "tool_use", "id": "tool_fixture", "name": "unapproved", "input": {}}
    )
    assert generate("claude", lambda _: httpx.Response(200, json=data)).status == "invalid_output"
