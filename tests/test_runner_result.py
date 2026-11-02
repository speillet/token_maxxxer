import json
from pathlib import Path

import pytest

from nightshift.runner_result import RunnerResult, normalize_result

FIXTURES = Path(__file__).parent / "fixtures/claude"


def successful_payload(**updates) -> str:
    payload = {"type": "result", "subtype": "success", "is_error": False, "result": "Done."}
    return json.dumps({**payload, **updates})


@pytest.mark.parametrize(
    ("fixture", "exit_code", "expected"),
    [
        ("success", 0, "success"),
        ("rate_limited", 1, "rate_limited"),
        ("auth_error", 1, "auth_error"),
        ("transient_error", 1, "transient_error"),
        ("internal_error", 0, "invalid_output"),
        ("success", 1, "invalid_output"),
    ],
)
def test_documented_terminal_scenarios(fixture, exit_code, expected) -> None:
    stdout = (FIXTURES / f"{fixture}.json").read_text()
    result = normalize_result(stdout, "", exit_code)
    assert result.status == expected
    assert result.exit_code == exit_code
    assert result.stdout == stdout


@pytest.mark.parametrize("payload", ["", "not json", "[]", "{}", "{", "null", "{}\n{}"])
def test_malformed_terminal_json(payload) -> None:
    assert normalize_result(payload, "rate limit reached", 1).status == "invalid_output"


@pytest.mark.parametrize(
    "updates",
    [
        {"is_error": "false"},
        {"is_error": 0},
        {"subtype": "future"},
        {"result": None},
        {"errors": ["Internal failure"]},
        {"api_error_status": 429},
        {"terminal_reason": "api_error"},
        {"usage": {"input_tokens": -1}},
        {"usage": {"output_tokens": True}},
        {"total_cost_usd": float("nan")},
        {"total_cost_usd": True},
    ],
)
def test_incoherent_success_is_never_accepted(updates) -> None:
    assert normalize_result(successful_payload(**updates), "", 0).status == "invalid_output"


def test_duplicate_json_keys_are_rejected() -> None:
    payload = '{"type":"result","subtype":"success","is_error":true,"is_error":false,"result":"ok"}'
    assert normalize_result(payload, "", 0).status == "invalid_output"


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
        (None, "invalid_output"),
    ],
)
def test_internal_error_takes_precedence_over_exit_zero(code, expected) -> None:
    payload = successful_payload(is_error=True, api_error_status=code)
    assert normalize_result(payload, "", 0).status == expected


def test_unknown_usage_is_not_zero() -> None:
    assert normalize_result(successful_payload(), "", 0).usage is None
    result = normalize_result(successful_payload(usage={"input_tokens": 0}), "", 0)
    assert result.usage.input_tokens == 0
    assert result.usage.output_tokens is None
    assert result.usage.estimated_cost_usd is None
    assert result.usage.resets_at is None
    limited = normalize_result((FIXTURES / "rate_limited.json").read_text(), "", 1)
    assert limited.usage.limit_reached is True
    assert limited.usage.input_tokens is None


def test_cost_and_session_metadata_are_retained() -> None:
    result = normalize_result(successful_payload(total_cost_usd=0, session_id="fixture"), "", 0)
    assert result.session_id == "fixture"
    assert result.usage.estimated_cost_usd == 0


def test_secrets_are_redacted_in_all_serialized_diagnostics() -> None:
    dummy_key = "sk-ant-fixture-credential"
    result = normalize_result(
        successful_payload(result=dummy_key),
        'Authorization: Bearer fixture-token\npassword="fixture-password"',
        0,
    )
    serialized = result.model_dump_json()
    for value in (dummy_key, "fixture-token", "fixture-password"):
        assert value not in serialized
    assert "[REDACTED]" in serialized
    assert dummy_key not in repr(result)
    assert dummy_key not in RunnerResult(status="success", text=dummy_key).text
