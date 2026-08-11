"""Write-only provider credential storage outside configuration and SQLite."""

from dataclasses import dataclass
from typing import Literal, Protocol

from radar.settings import EnvironmentSettings

ProviderName = Literal["openai", "anthropic", "google", "wafer"]
CredentialSource = Literal["environment", "keychain"]
_SERVICE = "github-opportunity-radar"
_ENVIRONMENT_FIELDS: dict[ProviderName, str] = {
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "google": "google_api_key",
    "wafer": "wafer_api_key",
}


class SecretStoreUnavailableError(RuntimeError):
    """No safe operating-system credential store is available."""


class SecretStore(Protocol):
    def get(self, provider: ProviderName) -> str | None: ...

    def set(self, provider: ProviderName, value: str) -> None: ...

    def delete(self, provider: ProviderName) -> None: ...


class NullSecretStore:
    """Fail-closed store used for tests and headless environment-only operation."""

    def get(self, provider: ProviderName) -> str | None:
        del provider
        return None

    def set(self, provider: ProviderName, value: str) -> None:
        del provider, value
        raise SecretStoreUnavailableError("operating-system credential storage is unavailable")

    def delete(self, provider: ProviderName) -> None:
        del provider
        raise SecretStoreUnavailableError("operating-system credential storage is unavailable")


class KeyringSecretStore:
    """Store secrets using the operating system's credential vault via keyring."""

    @staticmethod
    def _module() -> object:
        try:
            import keyring
        except ImportError as error:  # pragma: no cover - packaging failure
            raise SecretStoreUnavailableError("keyring is not installed") from error
        return keyring

    def get(self, provider: ProviderName) -> str | None:
        keyring = self._module()
        try:
            return keyring.get_password(_SERVICE, provider)  # type: ignore[attr-defined,no-any-return]
        except Exception as error:
            raise SecretStoreUnavailableError("credential vault could not be read") from error

    def set(self, provider: ProviderName, value: str) -> None:
        keyring = self._module()
        try:
            keyring.set_password(_SERVICE, provider, value)  # type: ignore[attr-defined]
        except Exception as error:
            raise SecretStoreUnavailableError("credential vault could not be written") from error

    def delete(self, provider: ProviderName) -> None:
        keyring = self._module()
        try:
            keyring.delete_password(_SERVICE, provider)  # type: ignore[attr-defined]
        except Exception as error:
            # Deleting an absent value is intentionally idempotent across backends.
            if error.__class__.__name__ != "PasswordDeleteError":
                raise SecretStoreUnavailableError(
                    "credential vault could not be updated"
                ) from error


@dataclass(frozen=True)
class ResolvedCredential:
    value: str | None
    source: CredentialSource | None


class CredentialResolver:
    """Resolve environment credentials before a write-only local vault."""

    def __init__(self, environment: EnvironmentSettings, store: SecretStore | None = None) -> None:
        self._environment = environment
        self._store = store or NullSecretStore()

    def resolve(self, provider: ProviderName) -> ResolvedCredential:
        environment_value = getattr(self._environment, _ENVIRONMENT_FIELDS[provider])
        if environment_value is not None and environment_value.strip():
            return ResolvedCredential(environment_value.strip(), "environment")
        value = self._store.get(provider)
        if value is not None and value.strip():
            return ResolvedCredential(value.strip(), "keychain")
        return ResolvedCredential(None, None)

    def save(self, provider: ProviderName, value: str) -> None:
        normalized = value.strip()
        if len(normalized) < 8 or len(normalized) > 4096:
            raise ValueError("credential must contain 8 to 4096 non-whitespace characters")
        self._store.set(provider, normalized)

    def delete(self, provider: ProviderName) -> None:
        self._store.delete(provider)

    def values_for_redaction(self) -> tuple[str, ...]:
        values: list[str] = []
        for provider in _ENVIRONMENT_FIELDS:
            try:
                credential = self.resolve(provider).value
            except SecretStoreUnavailableError:
                credential = None
            if credential:
                values.append(credential)
        return tuple(values)
