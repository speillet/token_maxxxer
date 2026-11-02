import json

import pytest

from token_maxxxer.redaction import redact
from token_maxxxer.results import GenerationResult


@pytest.mark.parametrize("name", ["password", "access_token", "client_secret", "ANTHROPIC_API_KEY"])
@pytest.mark.parametrize("secret", ["fixture-secret", "fixture secret with spaces"])
def test_credentials_embedded_in_json_are_absent_from_every_diagnostic(name, secret) -> None:
    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": f'{name}="{secret}"',
    }
    result = GenerationResult(status="success", text=json.dumps(payload))
    assert result.status == "success"
    assert secret not in result.text
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


@pytest.mark.parametrize("secret", ["sk-ant-fixture-credential", "access_token=fixture-token"])
def test_duplicate_json_keys_never_preserve_overwritten_credentials(secret) -> None:
    payload = (
        '{"type":"result","subtype":"success","is_error":false,'
        f'"result":{json.dumps(secret)},"result":"Done."}}'
    )
    result = GenerationResult(status="success", text=payload)
    for output in (result.text, result.model_dump_json()):
        assert secret not in output
        assert "fixture-token" not in output


def test_quoted_multiline_credential_is_redacted_entirely() -> None:
    payload = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": 'password="fixture-secret\ncontinuation-private"',
        }
    )
    result = GenerationResult(status="success", text=payload)
    for output in (result.text, result.model_dump_json()):
        assert "fixture-secret" not in output
        assert "continuation-private" not in output


@pytest.mark.parametrize(
    "credential", ["sk-legacy-fixture", "github_pat_fixture_value", "ghp_fixture_value"]
)
def test_credentials_from_other_providers_are_redacted(credential) -> None:
    assert credential not in redact("response contains " + credential)
