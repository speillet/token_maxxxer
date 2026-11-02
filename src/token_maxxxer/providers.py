"""Provider-independent text generation with explicit API credentials and no retries."""

import time
from typing import Protocol

import anthropic
import httpx
import openai
from pydantic import Field, SecretStr

from token_maxxxer.config import ProviderConfig
from token_maxxxer.models import Model, Text, UsageObservation, utc_now
from token_maxxxer.runner_result import RunnerResult, RunnerStatus


class GenerationRequest(Model):
    prompt: Text = Field(repr=False, max_length=1_048_576)
    settings: ProviderConfig


class Provider(Protocol):
    def generate(self, request: GenerationRequest, credential: SecretStr) -> RunnerResult: ...


class UnsupportedProviderError(ValueError):
    """A provider is recognized but has not been integrated yet."""


def _api_failure(error: Exception, started: float) -> RunnerResult:
    status: RunnerStatus = "invalid_output"
    code = "invalid_api_response"
    if isinstance(error, (anthropic.APITimeoutError, openai.APITimeoutError)):
        status, code = "timeout", "api_timeout"
    elif isinstance(error, (anthropic.APIConnectionError, openai.APIConnectionError)):
        status, code = "transient_error", "api_connection_failed"
    elif isinstance(error, (anthropic.APIStatusError, openai.APIStatusError)):
        if error.status_code in (401, 403):
            status, code = "auth_error", "api_authentication_failed"
        elif error.status_code == 429:
            status, code = "rate_limited", "api_rate_limited"
        elif error.status_code == 408 or error.status_code >= 500:
            status, code = "transient_error", "api_unavailable"
        else:
            code = "api_request_rejected"
    # Exception strings, response bodies and headers can contain credentials.
    return RunnerResult(status=status, error_code=code, duration_seconds=time.monotonic() - started)


class AnthropicProvider:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._transport = transport

    def generate(self, request: GenerationRequest, credential: SecretStr) -> RunnerResult:
        started = time.monotonic()
        try:
            with anthropic.Anthropic(
                api_key=credential.get_secret_value(),
                base_url="https://api.anthropic.com",
                timeout=request.settings.timeout_seconds,
                max_retries=0,
                _strict_response_validation=True,
                http_client=httpx.Client(
                    transport=self._transport, trust_env=False, follow_redirects=False
                ),
            ) as client:
                message = client.messages.create(
                    model=request.settings.model,
                    max_tokens=request.settings.max_output_tokens,
                    messages=[{"role": "user", "content": request.prompt}],
                )
            text = "".join(block.text for block in message.content if block.type == "text")
            complete = (
                message.stop_reason in ("end_turn", "stop_sequence")
                and bool(text.strip())
                and all(
                    block.type in ("text", "thinking", "redacted_thinking")
                    for block in message.content
                )
            )
            return RunnerResult(
                status="success" if complete else "invalid_output",
                text=text,
                session_id=message.id,
                error_code=None if complete else "incomplete_generation",
                duration_seconds=time.monotonic() - started,
                usage=UsageObservation(
                    observed_at=utc_now(),
                    source="claude_api",
                    input_tokens=message.usage.input_tokens,
                    output_tokens=message.usage.output_tokens,
                ),
            )
        except (anthropic.APIError, ValueError, TypeError, AttributeError) as error:
            return _api_failure(error, started)


class OpenAIProvider:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._transport = transport

    def generate(self, request: GenerationRequest, credential: SecretStr) -> RunnerResult:
        started = time.monotonic()
        try:
            with openai.OpenAI(
                api_key=credential.get_secret_value(),
                base_url="https://api.openai.com/v1",
                timeout=request.settings.timeout_seconds,
                max_retries=0,
                _strict_response_validation=True,
                http_client=httpx.Client(
                    transport=self._transport, trust_env=False, follow_redirects=False
                ),
            ) as client:
                response = client.responses.create(
                    model=request.settings.model,
                    input=request.prompt,
                    max_output_tokens=request.settings.max_output_tokens,
                    store=False,
                )
            complete = (
                response.status == "completed"
                and response.error is None
                and response.incomplete_details is None
                and bool(response.output_text.strip())
            )
            for item in response.output:
                if item.type == "message":
                    complete = (
                        complete
                        and item.status == "completed"
                        and all(block.type == "output_text" for block in item.content)
                    )
                elif item.type == "reasoning":
                    complete = complete and item.status in (None, "completed")
                else:
                    # This text-only port does not execute or satisfy tool calls.
                    complete = False
            usage = None
            if response.usage is not None:
                usage = UsageObservation(
                    observed_at=utc_now(),
                    source="openai_api",
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                )
            return RunnerResult(
                status="success" if complete else "invalid_output",
                text=response.output_text,
                session_id=response.id,
                error_code=None if complete else "incomplete_generation",
                duration_seconds=time.monotonic() - started,
                usage=usage,
            )
        except (openai.APIError, ValueError, TypeError, AttributeError) as error:
            return _api_failure(error, started)


def create_provider(
    settings: ProviderConfig, *, transport: httpx.BaseTransport | None = None
) -> Provider:
    if settings.name == "claude":
        return AnthropicProvider(transport)
    if settings.name == "openai":
        return OpenAIProvider(transport)
    raise UnsupportedProviderError(
        "Copilot nécessite son SDK officiel et un token GitHub autorisé ; adaptateur indisponible"
    )
