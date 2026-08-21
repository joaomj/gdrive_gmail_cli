"""Black-box tests for CLI behavior that does not require live Google access."""

from __future__ import annotations

import pytest

from google_personal_cli.cli import main


def test_auth_login_reports_missing_client_file(capsys) -> None:
    """Authentication setup returns a structured local error."""
    exit_code = main(
        [
            "auth",
            "login",
            "--client-id-file",
            "/path/that/does/not/exist.json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 7
    assert '"code": "local"' in captured.err
    assert captured.out == ""


def test_gmail_thread_uses_resource_action_syntax(capsys) -> None:
    """The documented Gmail resource syntax is available at the CLI boundary."""
    with pytest.raises(SystemExit) as result:
        main(["gmail", "thread", "get", "--help"])

    captured = capsys.readouterr()
    assert result.value.code == 0
    assert "usage: gpersonal gmail thread get" in captured.out
