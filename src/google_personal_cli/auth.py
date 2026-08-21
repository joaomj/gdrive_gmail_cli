"""Direct desktop OAuth and macOS Keychain credential storage."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import keyring
import requests
from google.auth.credentials import Credentials
from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from keyring.errors import KeyringError
from oauthlib.oauth2.rfc6749.errors import OAuth2Error
from requests import RequestException

from google_personal_cli.config import (
    DEFAULT_TIMEOUT_SECONDS,
    KEYRING_ACCOUNT,
    KEYRING_SERVICE,
    OAUTH_REVOKE_MISSING_STATUS,
    OAUTH_REVOKE_SUCCESS_STATUS,
    OAUTH_REVOKE_URL,
    OAUTH_SCOPES,
    Settings,
)
from google_personal_cli.errors import AuthenticationError, LocalError


@dataclass(frozen=True)
class AuthStatus:
    """Safe authentication status without credential material."""

    authenticated: bool
    source: str
    project_id: str | None
    scopes: tuple[str, ...]


def _read_secret() -> str | None:
    """Read the serialized OAuth credential from the OS credential store."""
    try:
        return keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except KeyringError as error:
        raise LocalError("macOS Keychain could not be read") from error


def _credentials_from_secret(secret: str) -> UserCredentials:
    """Deserialize and validate the stored OAuth credential."""
    try:
        info = json.loads(secret)
    except json.JSONDecodeError as error:
        raise AuthenticationError("The Keychain OAuth credential is invalid") from error
    if not isinstance(info, dict):
        raise AuthenticationError("The Keychain OAuth credential is invalid")
    try:
        return UserCredentials.from_authorized_user_info(info, scopes=list(OAUTH_SCOPES))
    except (TypeError, ValueError) as error:
        raise AuthenticationError("The Keychain OAuth credential is incomplete") from error


def _read_credentials() -> UserCredentials | None:
    """Load the user credential without exposing its serialized value."""
    secret = _read_secret()
    if secret is None:
        return None
    return _credentials_from_secret(secret)


def _store_credentials(credentials: UserCredentials) -> None:
    """Store the serialized OAuth credential in macOS Keychain."""
    try:
        keyring.set_password(
            KEYRING_SERVICE,
            KEYRING_ACCOUNT,
            credentials.to_json(),
        )
    except KeyringError as error:
        raise LocalError("macOS Keychain could not store the OAuth credential") from error


def _delete_credentials() -> None:
    """Remove the local OAuth credential from macOS Keychain."""
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except KeyringError as error:
        raise LocalError("macOS Keychain could not remove the OAuth credential") from error


def load_credentials() -> tuple[Credentials, str | None]:
    """Load and refresh the user's OAuth credential from macOS Keychain."""
    credentials = _read_credentials()
    if credentials is None:
        raise AuthenticationError(
            "No Google authorization is stored. Run `gpersonal auth login --client-id-file PATH`."
        )
    if not credentials.valid:
        try:
            credentials.refresh(Request())
        except RefreshError as error:
            raise AuthenticationError(
                "Google authorization expired. Run `gpersonal auth login --client-id-file PATH`."
            ) from error
        _store_credentials(credentials)
    return credentials, None


def check_authentication() -> AuthStatus:
    """Refresh OAuth credentials and return safe status information."""
    credentials, _ = load_credentials()
    if not credentials.valid:
        raise AuthenticationError("Google authorization is not valid")
    return AuthStatus(
        authenticated=True,
        source="macOS Keychain",
        project_id=None,
        scopes=OAUTH_SCOPES,
    )


def login(client_id_file: Path, no_browser: bool) -> None:
    """Authorize the user through the desktop OAuth loopback flow."""
    if not client_id_file.is_file():
        raise LocalError(f"OAuth client file does not exist: {client_id_file}")
    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_id_file),
            scopes=list(OAUTH_SCOPES),
        )
        credentials = flow.run_local_server(
            port=0,
            open_browser=not no_browser,
            access_type="offline",
            prompt="consent",
        )
    except (GoogleAuthError, OAuth2Error, OSError, RequestException, ValueError) as error:
        raise AuthenticationError(
            "Google OAuth login failed. Check the OAuth client, consent screen, and test user."
        ) from error
    if not isinstance(credentials, UserCredentials):
        raise AuthenticationError("Google OAuth login returned an invalid credential")
    if not credentials.refresh_token:
        raise AuthenticationError(
            "Google OAuth login returned no refresh credential. Run login again and approve access."
        )
    _store_credentials(credentials)


def revoke(settings: Settings | None = None) -> None:
    """Revoke the Google refresh token and remove the local Keychain entry."""
    credentials = _read_credentials()
    if credentials is None:
        return
    refresh_token = credentials.refresh_token
    if refresh_token:
        timeout = settings.timeout_seconds if settings is not None else DEFAULT_TIMEOUT_SECONDS
        try:
            response = requests.post(
                OAUTH_REVOKE_URL,
                data={"token": refresh_token},
                timeout=timeout,
            )
        except RequestException as error:
            raise AuthenticationError("Google authorization could not be revoked") from error
        if response.status_code not in {
            OAUTH_REVOKE_SUCCESS_STATUS,
            OAUTH_REVOKE_MISSING_STATUS,
        }:
            raise AuthenticationError("Google authorization could not be revoked")
    _delete_credentials()
