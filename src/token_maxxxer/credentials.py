"""Resolve provider credentials without exposing them or modifying the environment."""

import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

from pydantic import SecretStr

from token_maxxxer.config import ProviderConfig

KEY_VARIABLES = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "copilot": "COPILOT_GITHUB_TOKEN",
}
REFERENCE_VARIABLES = {
    name: f"TOKEN_MAXXXER_{name.upper()}_CREDENTIAL_REF" for name in KEY_VARIABLES
}
_IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,199}$")


class CredentialError(ValueError):
    """A credential resolution failure with no secret in its message."""


def _references(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise CredentialError("the reference file must be a regular local file")
    with path.open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise CredentialError("reference file is too large")
    try:
        content = raw.decode("utf-8")
    except UnicodeError as exc:
        raise CredentialError("expected a UTF-8 reference file") from exc
    values: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        name = name.strip()
        if name in KEY_VARIABLES.values():
            raise CredentialError("store a reference in .env, never an API key value")
        if name not in REFERENCE_VARIABLES.values():
            continue
        if not separator or name in values:
            raise CredentialError("invalid or duplicate .env reference")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
    return values


def _reference(provider: ProviderConfig, path: Path, environment: Mapping[str, str]) -> str | None:
    name = REFERENCE_VARIABLES[provider.name]
    return environment.get(name) or _references(path).get(name)


def _keychain_coordinates(reference: str) -> tuple[str, str]:
    parsed = urlparse(reference)
    account = parsed.path.removeprefix("/")
    if (
        parsed.scheme != "keychain"
        or parsed.query
        or parsed.fragment
        or not _IDENTIFIER.fullmatch(parsed.netloc)
        or not _IDENTIFIER.fullmatch(account)
    ):
        raise CredentialError("expected reference: keychain://service/account")
    return parsed.netloc, account


def credential_configured(
    provider: ProviderConfig,
    path: Path,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Check configuration without retrieving a Keychain value or making a request."""
    environment = os.environ if environment is None else environment
    if environment.get(KEY_VARIABLES[provider.name]):
        return True
    reference = _reference(provider, path, environment)
    if reference:
        _keychain_coordinates(reference)
        return True
    return False


def resolve_credential(
    provider: ProviderConfig,
    path: Path,
    environment: Mapping[str, str] | None = None,
) -> SecretStr:
    environment = os.environ if environment is None else environment
    secret = environment.get(KEY_VARIABLES[provider.name])
    if not secret:
        reference = _reference(provider, path, environment)
        if not reference:
            raise CredentialError("API key is missing for the selected provider")
        service, account = _keychain_coordinates(reference)
        if sys.platform != "darwin":
            raise CredentialError(
                "Keychain references require macOS; use the API environment variable"
            )
        try:
            result = subprocess.run(
                ["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CredentialError("cannot read the credential manager") from exc
        if result.returncode != 0 or len(result.stdout) > 4096:
            raise CredentialError("credential is inaccessible in Keychain")
        try:
            secret = result.stdout.decode("ascii").removesuffix("\n")
        except UnicodeError as exc:
            raise CredentialError("invalid credential format") from exc
    if not secret or len(secret) > 4096 or any(not 33 <= ord(char) <= 126 for char in secret):
        raise CredentialError("invalid credential format")
    return SecretStr(secret)
