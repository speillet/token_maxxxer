import subprocess

import pytest

from token_maxxxer.config import ProviderConfig
from token_maxxxer.credentials import CredentialError, credential_configured, resolve_credential


def settings(name="claude") -> ProviderConfig:
    return ProviderConfig(name=name, model="fixture-model")


def test_environment_key_is_selected_without_loading_another_provider(tmp_path) -> None:
    environment = {"ANTHROPIC_API_KEY": "sk-fixture-claude", "OPENAI_API_KEY": "sk-fixture-openai"}
    assert (
        resolve_credential(settings(), tmp_path / ".env", environment).get_secret_value()
        == "sk-fixture-claude"
    )
    value = resolve_credential(settings("openai"), tmp_path / ".env", environment)
    assert value.get_secret_value() == "sk-fixture-openai"
    assert "sk-fixture-openai" not in repr(value)
    assert environment == {
        "ANTHROPIC_API_KEY": "sk-fixture-claude",
        "OPENAI_API_KEY": "sk-fixture-openai",
    }


def test_reference_status_does_not_read_keychain(tmp_path, monkeypatch) -> None:
    path = tmp_path / ".env"
    path.write_text("TOKEN_MAXXXER_CLAUDE_CREDENTIAL_REF=keychain://fixture/account\n")

    def forbidden(*args, **kwargs):
        raise AssertionError("doctor must not read a credential")

    monkeypatch.setattr("token_maxxxer.credentials.subprocess.run", forbidden)
    assert credential_configured(settings(), path, {}) is True


def test_keychain_is_resolved_only_on_request_and_never_logged(tmp_path, monkeypatch) -> None:
    path = tmp_path / ".env"
    path.write_text("TOKEN_MAXXXER_CLAUDE_CREDENTIAL_REF='keychain://fixture/account'\n")
    monkeypatch.setattr("token_maxxxer.credentials.sys.platform", "darwin")
    captured = []

    def execute(arguments, **kwargs):
        captured.append((arguments, kwargs))
        return subprocess.CompletedProcess(arguments, 0, stdout=b"sk-fixture-value\n")

    monkeypatch.setattr("token_maxxxer.credentials.subprocess.run", execute)
    secret = resolve_credential(settings(), path, {})
    assert secret.get_secret_value() == "sk-fixture-value"
    assert "sk-fixture-value" not in repr(secret)
    assert captured[0][0] == [
        "/usr/bin/security",
        "find-generic-password",
        "-s",
        "fixture",
        "-a",
        "account",
        "-w",
    ]
    assert captured[0][1]["timeout"] == 10


@pytest.mark.parametrize(
    "value",
    ["keychain://fixture/--option", "https://untrusted/key", "keychain://fixture/account?x=1"],
)
def test_bad_references_are_rejected_without_processes(tmp_path, value) -> None:
    with pytest.raises(CredentialError):
        credential_configured(
            settings(), tmp_path / ".env", {"TOKEN_MAXXXER_CLAUDE_CREDENTIAL_REF": value}
        )


def test_plaintext_dotenv_keys_and_duplicates_are_rejected(tmp_path) -> None:
    path = tmp_path / ".env"
    for content in [
        "ANTHROPIC_API_KEY=sk-fixture-value\n",
        "TOKEN_MAXXXER_CLAUDE_CREDENTIAL_REF=x\nTOKEN_MAXXXER_CLAUDE_CREDENTIAL_REF=y\n",
    ]:
        path.write_text(content)
        with pytest.raises(CredentialError) as error:
            credential_configured(settings(), path, {})
        assert "sk-fixture-value" not in str(error.value)


@pytest.mark.parametrize("value", ["contains space", "bad\nvalue", "é", "x" * 4097])
def test_bad_credential_values_are_not_echoed(tmp_path, value) -> None:
    with pytest.raises(CredentialError, match="format de credential invalide"):
        resolve_credential(settings(), tmp_path / ".env", {"ANTHROPIC_API_KEY": value})


def test_missing_key_does_not_fall_back_to_another_provider(tmp_path) -> None:
    with pytest.raises(CredentialError, match="absente"):
        resolve_credential(settings(), tmp_path / ".env", {"OPENAI_API_KEY": "sk-fixture-openai"})
