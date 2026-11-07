"""An opt-in, ordered provider chain; each generate call is exactly one attempt."""

import time
from collections.abc import Callable

from pydantic import SecretStr

from token_maxxxer.config import ProviderConfig
from token_maxxxer.credentials import CredentialError
from token_maxxxer.providers import GenerationRequest, Provider, create_provider
from token_maxxxer.redaction import redact
from token_maxxxer.results import GenerationResult


class ProviderRouter:
    def __init__(
        self,
        settings: ProviderConfig,
        provider: Provider,
        credential_resolver: Callable[[ProviderConfig], SecretStr],
        factory: Callable[[ProviderConfig], Provider] = create_provider,
    ):
        self.chain = (settings, *settings.fallbacks)
        self.index = 0
        self.provider: Provider | None = provider
        self.credential: SecretStr | None = None
        self.credential_resolver = credential_resolver
        self.factory = factory

    @property
    def active(self) -> ProviderConfig:
        return self.chain[self.index]

    def advance(self, result: GenerationResult) -> bool:
        if result.status not in self.chain[0].fallback_on or self.index + 1 >= len(self.chain):
            return False
        self.index += 1
        self.provider = None
        self.credential = None
        return True

    def generate(self, request: GenerationRequest, credential: SecretStr) -> GenerationResult:
        started = time.monotonic()
        try:
            if self.provider is None:
                selected_credential = self.credential_resolver(self.active)
                self.provider = self.factory(self.active)
                self.credential = selected_credential
            remaining = request.settings.timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                return GenerationResult(status="timeout", error_code="provider_chain_timeout")
            settings = self.active.model_copy(
                update={"timeout_seconds": min(self.active.timeout_seconds, remaining)}
            )
            result = self.provider.generate(
                request.model_copy(update={"settings": settings}),
                self.credential if self.credential is not None else credential,
            )
        except CredentialError:
            result = GenerationResult(
                status="auth_error", error_code="fallback_credential_unavailable"
            )
        return result.model_copy(
            update={"provider": self.active.name, "model": redact(self.active.model)}
        )


def with_fallbacks(
    provider: Provider,
    settings: ProviderConfig,
    credential_resolver: Callable[[ProviderConfig], SecretStr],
    factory: Callable[[ProviderConfig], Provider] = create_provider,
) -> Provider:
    return (
        ProviderRouter(settings, provider, credential_resolver, factory)
        if settings.fallbacks
        else provider
    )


def active_settings(provider: Provider, default: ProviderConfig) -> ProviderConfig:
    return provider.active if isinstance(provider, ProviderRouter) else default


def advance_provider(provider: Provider, result: GenerationResult) -> bool:
    return isinstance(provider, ProviderRouter) and provider.advance(result)


def generate_query(
    provider: Provider,
    request: GenerationRequest,
    credential: SecretStr,
) -> GenerationResult:
    started = time.monotonic()
    deadline = started + request.settings.timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return GenerationResult(status="timeout", error_code="provider_chain_timeout")
        bounded = request.model_copy(
            update={"settings": request.settings.model_copy(update={"timeout_seconds": remaining})}
        )
        result = provider.generate(bounded, credential)
        if not advance_provider(provider, result):
            return result.model_copy(update={"duration_seconds": time.monotonic() - started})
