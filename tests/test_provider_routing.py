import json
import sys

import pytest
from pydantic import SecretStr, ValidationError

from token_maxxxer.cli import main
from token_maxxxer.config import ProviderConfig
from token_maxxxer.credentials import CredentialError
from token_maxxxer.night import NightPlan, run_night
from token_maxxxer.provider_routing import ProviderRouter, generate_query, with_fallbacks
from token_maxxxer.providers import GenerationRequest
from token_maxxxer.results import GenerationResult
from token_maxxxer.skills import discover_skills, select_skill


class Responses:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def generate(self, request, credential):
        self.requests.append((request, credential.get_secret_value()))
        value = next(self.responses)
        if isinstance(value, GenerationResult):
            return value
        return GenerationResult(status="success", text=json.dumps({"action": value}))


def configuration(**changes):
    return ProviderConfig(
        name="claude",
        model="primary",
        fallbacks=(ProviderConfig(name="codex", model="secondary"),),
        **changes,
    )


@pytest.mark.parametrize(
    "status", ["auth_error", "transient_error", "timeout", "invalid_output", "rate_limited"]
)
def test_unconfigured_failures_do_not_switch_or_resolve_other_credentials(status):
    settings = configuration()
    original = Responses(GenerationResult(status=status))

    def forbidden(*args):
        raise AssertionError("a non-quota error cannot select another provider")

    router = ProviderRouter(settings, original, forbidden, forbidden)
    result = generate_query(
        router, GenerationRequest(prompt="Prompt", settings=settings), SecretStr("primary-key")
    )
    assert result.status == status
    assert router.index == 0


def test_empty_cli_credential_never_reuses_the_primary_api_key_and_selection_is_sticky():
    settings = configuration()
    primary = Responses(GenerationResult(status="quota_exhausted"))
    secondary = Responses(
        GenerationResult(status="success", text="First"),
        GenerationResult(status="success", text="Next"),
    )
    resolved = []

    def resolve(target):
        resolved.append(target.name)
        return SecretStr("")

    router = ProviderRouter(settings, primary, resolve, lambda target: secondary)
    request = GenerationRequest(prompt="Same context", settings=settings)
    first = generate_query(router, request, SecretStr("primary-key"))
    second = generate_query(router, request, SecretStr("primary-key"))
    assert first.provider == second.provider == "codex"
    assert first.model == second.model == "secondary"
    assert resolved == ["codex"]
    assert len(primary.requests) == 1
    assert [credential for _, credential in secondary.requests] == ["", ""]
    assert all(item.prompt == "Same context" for item, _ in secondary.requests)


def test_fallback_authentication_failure_is_explicit_and_not_retried():
    settings = configuration()

    def denied(target):
        raise CredentialError("not logged in")

    router = ProviderRouter(
        settings,
        Responses(GenerationResult(status="quota_exhausted")),
        denied,
        lambda target: Responses(),
    )
    result = generate_query(
        router, GenerationRequest(prompt="Prompt", settings=settings), SecretStr("primary-key")
    )
    assert result.status == "auth_error"
    assert result.error_code == "fallback_credential_unavailable"
    again = generate_query(
        router, GenerationRequest(prompt="Prompt", settings=settings), SecretStr("primary-key")
    )
    assert again.status == "auth_error"


def test_all_configured_allocations_exhaust_without_replaying_a_provider():
    settings = ProviderConfig(
        name="claude",
        model="primary",
        fallbacks=(
            ProviderConfig(name="codex", model="second"),
            ProviderConfig(name="copilot", model="third"),
        ),
    )
    attempted = []

    class Empty:
        def generate(self, request, credential):
            attempted.append(request.settings.name)
            return GenerationResult(status="quota_exhausted")

    router = ProviderRouter(settings, Empty(), lambda target: SecretStr(""), lambda target: Empty())
    result = generate_query(
        router, GenerationRequest(prompt="Prompt", settings=settings), SecretStr("")
    )
    assert result.status == "quota_exhausted"
    assert attempted == ["claude", "codex", "copilot"]


def test_credential_lookup_consumes_the_remaining_query_timeout(monkeypatch):
    ticks = [0.0]
    monkeypatch.setattr("token_maxxxer.provider_routing.time.monotonic", lambda: ticks[0])
    settings = configuration(timeout_seconds=1)

    def slow_credentials(target):
        ticks[0] = 2
        return SecretStr("")

    secondary = Responses()
    router = ProviderRouter(
        settings,
        Responses(GenerationResult(status="quota_exhausted")),
        slow_credentials,
        lambda target: secondary,
    )
    result = generate_query(
        router, GenerationRequest(prompt="Prompt", settings=settings), SecretStr("")
    )
    assert result.status == "timeout"
    assert not secondary.requests


def test_query_deadline_prevents_launching_the_next_provider(monkeypatch):
    ticks = [0.0]
    monkeypatch.setattr("token_maxxxer.provider_routing.time.monotonic", lambda: ticks[0])
    settings = configuration(timeout_seconds=1)

    class SlowQuota:
        def generate(self, request, credential):
            ticks[0] = 2
            return GenerationResult(status="quota_exhausted")

    def forbidden(*args):
        raise AssertionError("deadline elapsed before fallback")

    router = ProviderRouter(settings, SlowQuota(), forbidden, forbidden)
    result = generate_query(
        router, GenerationRequest(prompt="Prompt", settings=settings), SecretStr("")
    )
    assert result.status == "timeout"


def test_rate_limit_switch_requires_explicit_opt_in():
    settings = configuration(fallback_on=("quota_exhausted", "rate_limited"))
    router = ProviderRouter(
        settings,
        Responses(GenerationResult(status="rate_limited")),
        lambda target: SecretStr(""),
        lambda target: Responses(GenerationResult(status="success", text="Done")),
    )
    assert (
        generate_query(
            router, GenerationRequest(prompt="Prompt", settings=settings), SecretStr("")
        ).status
        == "success"
    )


@pytest.mark.parametrize(
    "fallbacks",
    [
        [{"name": "claude", "model": "primary"}],
        [
            {
                "name": "codex",
                "model": "secondary",
                "fallbacks": [{"name": "openai", "model": "third"}],
            }
        ],
        [{"name": "codex", "model": str(index)} for index in range(4)],
    ],
)
def test_recursive_duplicate_and_unbounded_chains_are_rejected(fallbacks):
    with pytest.raises(ValidationError):
        ProviderConfig(name="claude", model="primary", fallbacks=fallbacks)


def test_no_chain_preserves_the_existing_provider():
    original = Responses()
    assert (
        with_fallbacks(original, ProviderConfig(model="primary"), lambda target: SecretStr(""))
        is original
    )


def test_night_switch_preserves_context_files_checks_and_call_accounting(repository, tmp_path):
    settings = configuration()
    primary = Responses(
        {"type": "read_file", "path": "main.py"},
        GenerationResult(status="quota_exhausted", error_code="api_quota_exhausted"),
    )
    secondary = Responses(
        {"type": "write_file", "path": "main.py", "content": "print('verified')\n"},
        {"type": "finish", "summary": "Verified the change."},
    )
    router = ProviderRouter(
        settings, primary, lambda target: SecretStr(""), lambda target: secondary
    )
    plan = NightPlan(
        repository=repository,
        skill="builtin:improve-code",
        provider=settings,
        max_calls=4,
        verification_commands=((sys.executable, "-B", "-c", "import main"),),
    )
    skill = select_skill(discover_skills(repository), plan.skill, mode="edit")
    session = run_night(plan, skill, tmp_path / "state", router, SecretStr("primary-key"))
    assert session.state == "completed"
    assert session.calls == 4
    assert (repository / "main.py").read_text() == "print('hello')\n"
    assert (session.worktree / "main.py").read_text() == "print('verified')\n"
    assert session.verification[0]["status"] == "passed"
    assert "print('hello')" in secondary.requests[0][0].prompt
    assert secondary.requests[0][0].settings.model == "secondary"
    switches = [event for event in session.events if event.get("type") == "provider_switch"]
    assert len(switches) == 1 and switches[0]["to"] == "codex"
    assert "primary-key" not in (tmp_path / "state/runs" / session.id / "session.json").read_text()


def test_call_limit_does_not_allow_an_extra_fallback_request(repository, tmp_path):
    settings = configuration()

    def forbidden(*args):
        raise AssertionError("call budget cannot be exceeded by a fallback")

    router = ProviderRouter(
        settings, Responses(GenerationResult(status="quota_exhausted")), forbidden, forbidden
    )
    plan = NightPlan(
        repository=repository, skill="builtin:improve-code", provider=settings, max_calls=1
    )
    skill = select_skill(discover_skills(repository), plan.skill, mode="edit")
    session = run_night(plan, skill, tmp_path / "state", router, SecretStr(""))
    assert session.state == "failed" and session.reason == "quota_exhausted"
    assert session.calls == 1


def test_cli_previews_authorized_chain_without_credentials_or_state(
    repository, tmp_path, monkeypatch, capsys
):
    def forbidden(*args):
        raise AssertionError("preview cannot start any provider")

    monkeypatch.setattr("token_maxxxer.night_cli.resolve_credential", forbidden)
    monkeypatch.setattr("token_maxxxer.night_cli.create_provider", forbidden)
    state = tmp_path / "state"
    assert (
        main(
            [
                "--state-dir",
                str(state),
                "night",
                str(repository),
                "--provider",
                "claude",
                "--model",
                "primary",
                "--fallback",
                "codex:secondary",
                "--fallback",
                "copilot:third",
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )
    plan = json.loads(capsys.readouterr().out)["plan"]
    assert [provider["name"] for provider in plan["provider"]["fallbacks"]] == ["codex", "copilot"]
    assert not state.exists()


def test_query_cli_applies_yaml_fallback_and_reports_the_actual_model(
    config_path, tmp_path, monkeypatch, capsys
):
    import yaml

    document = yaml.safe_load(config_path.read_text())
    document["provider"] = configuration().model_dump(mode="json")
    config_path.write_text(yaml.safe_dump(document), encoding="utf-8")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Pending context", encoding="utf-8")
    primary = Responses(GenerationResult(status="quota_exhausted"))
    secondary = Responses(GenerationResult(status="success", text="Done"))
    monkeypatch.setattr(
        "token_maxxxer.cli.create_provider",
        lambda settings: primary if settings.name == "claude" else secondary,
    )
    credentials = []

    def resolve(settings, path):
        credentials.append(settings.name)
        return SecretStr("primary-secret" if settings.name == "claude" else "")

    monkeypatch.setattr("token_maxxxer.cli.resolve_credential", resolve)
    assert (
        main(["--config", str(config_path), "query", "--prompt-file", str(prompt), "--json"]) == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["provider"] == "codex" and result["model"] == "secondary"
    assert credentials == ["claude", "codex"]
    assert secondary.requests[0][1] == ""
    assert not (config_path.parent / "var").exists()
