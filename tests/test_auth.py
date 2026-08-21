"""Black-box authentication behavior through external OAuth and Keychain seams."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import keyring
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow

from google_personal_cli import auth
from google_personal_cli.config import OAUTH_SCOPES


def _credential() -> UserCredentials:
    """Create a valid OAuth credential for a deterministic test boundary."""
    return UserCredentials(
        token="access-token",
        refresh_token="refresh-token",
        token_uri="https://oauth2.example.test/token",
        client_id="client-id",
        client_secret="client-secret",
        scopes=list(OAUTH_SCOPES),
        expiry=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def test_login_stores_direct_oauth_credential_in_keychain(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Direct desktop OAuth stores the refreshable credential without gcloud."""
    client_file = tmp_path / "client.json"
    client_file.write_text("{}", encoding="utf-8")
    stored: dict[str, str] = {}
    flow_arguments: dict[str, object] = {}

    class FakeFlow:
        """External OAuth flow replacement with the same user-facing result."""

        def run_local_server(self, **kwargs: object) -> UserCredentials:
            flow_arguments.update(kwargs)
            return _credential()

    def create_flow(
        cls: type[InstalledAppFlow],
        filename: str,
        scopes: list[str],
    ) -> FakeFlow:
        flow_arguments["filename"] = filename
        flow_arguments["scopes"] = scopes
        return FakeFlow()

    def store_password(service: str, account: str, password: str) -> None:
        stored["service"] = service
        stored["account"] = account
        stored["password"] = password

    monkeypatch.setattr(
        InstalledAppFlow,
        "from_client_secrets_file",
        classmethod(create_flow),
    )
    monkeypatch.setattr(keyring, "set_password", store_password)

    auth.login(client_file, no_browser=True)

    assert flow_arguments["filename"] == str(client_file)
    assert flow_arguments["scopes"] == list(OAUTH_SCOPES)
    assert flow_arguments["open_browser"] is False
    assert json.loads(stored["password"])["refresh_token"] == "refresh-token"


def test_load_credentials_reads_valid_credential_from_keychain(monkeypatch) -> None:
    """API authentication loads a valid credential from Keychain without gcloud."""
    serialized = _credential().to_json()
    monkeypatch.setattr(keyring, "get_password", lambda service, account: serialized)

    credentials, project_id = auth.load_credentials()

    assert credentials.refresh_token == "refresh-token"
    assert project_id is None
