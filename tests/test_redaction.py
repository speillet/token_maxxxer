import json

import pytest

from nightshift.redaction import redact
from nightshift.runner_result import normalize_result


@pytest.mark.parametrize("name", ["password", "access_token", "client_secret", "ANTHROPIC_API_KEY"])
@pytest.mark.parametrize("secret", ["fixture-secret", "fixture secret with spaces"])
def test_credentials_embedded_in_json_are_absent_from_every_diagnostic(name, secret) -> None:
    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": f'{name}="{secret}"',
    }
    result = normalize_result(json.dumps(payload), "", 0)
    assert result.status == "success"
    assert secret not in result.text
    assert secret not in result.stdout
    assert secret not in result.model_dump_json()
    assert secret not in repr(result)


def test_nested_json_credentials_and_unrelated_fields() -> None:
    payload = {"items": [{"access_token": "fixture secret", "message": "preserved"}]}
    sanitized = redact(json.dumps(payload))
    assert "fixture secret" not in sanitized
    assert json.loads(sanitized)["items"][0]["message"] == "preserved"


@pytest.mark.parametrize("quoted", [False, True])
def test_truncated_json_is_still_expurgated(quoted) -> None:
    text = json.dumps({"result": 'password="fixture secret"'})[:-1]
    if quoted:
        text = json.dumps(text)[:-1]
    assert "fixture secret" not in redact(text)


def test_non_sensitive_text_and_json_are_preserved_exactly() -> None:
    for text in ["plain text", '{ "result": "done", "usage": null }\n']:
        assert redact(text) == text
