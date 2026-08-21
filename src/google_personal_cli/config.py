"""Central configuration for Google Personal CLI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final

GMAIL_SCOPE: Final[str] = "https://www.googleapis.com/auth/gmail.readonly"
DRIVE_SCOPE: Final[str] = "https://www.googleapis.com/auth/drive.readonly"
OAUTH_SCOPES: Final[tuple[str, str]] = (GMAIL_SCOPE, DRIVE_SCOPE)

GMAIL_API_BASE_URL: Final[str] = "https://gmail.googleapis.com/gmail/v1"
DRIVE_API_BASE_URL: Final[str] = "https://www.googleapis.com/drive/v3"
GOOGLE_USER_ID: Final[str] = "me"
URL_PATH_SEPARATOR: Final[str] = "/"
KEYRING_SERVICE: Final[str] = "com.opencode.google-personal-cli"
KEYRING_ACCOUNT: Final[str] = "default"
OAUTH_REVOKE_URL: Final[str] = "https://oauth2.googleapis.com/revoke"
OAUTH_REVOKE_SUCCESS_STATUS: Final[int] = 200
OAUTH_REVOKE_MISSING_STATUS: Final[int] = 400
RETRYABLE_HTTP_STATUS_CODES: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})
GMAIL_THREADS_PATH: Final[str] = f"users/{GOOGLE_USER_ID}/threads"
GMAIL_MESSAGES_PATH: Final[str] = f"users/{GOOGLE_USER_ID}/messages"
GMAIL_LABELS_PATH: Final[str] = f"users/{GOOGLE_USER_ID}/labels"
GMAIL_THREAD_PATH_TEMPLATE: Final[str] = f"{GMAIL_THREADS_PATH}/{{}}"
GMAIL_MESSAGE_PATH_TEMPLATE: Final[str] = f"{GMAIL_MESSAGES_PATH}/{{}}"
GMAIL_ATTACHMENT_PATH_TEMPLATE: Final[str] = f"{GMAIL_MESSAGES_PATH}/{{}}/attachments/{{}}"
DRIVE_FILE_PATH_TEMPLATE: Final[str] = "files/{}"
DRIVE_EXPORT_PATH_TEMPLATE: Final[str] = "files/{}/export"

DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
DEFAULT_RETRY_ATTEMPTS: Final[int] = 3
DEFAULT_BACKOFF_SECONDS: Final[float] = 0.5
DEFAULT_PAGE_SIZE: Final[int] = 25
MAX_PAGE_SIZE: Final[int] = 100
DEFAULT_MAX_DOWNLOAD_BYTES: Final[int] = 50_000_000
MAX_EXPORT_BYTES: Final[int] = 10_000_000
DOWNLOAD_CHUNK_BYTES: Final[int] = 64 * 1024

ENV_TIMEOUT_SECONDS: Final[str] = "GPERSONAL_TIMEOUT_SECONDS"
ENV_RETRY_ATTEMPTS: Final[str] = "GPERSONAL_RETRY_ATTEMPTS"
ENV_MAX_DOWNLOAD_BYTES: Final[str] = "GPERSONAL_MAX_DOWNLOAD_BYTES"


def _read_float(name: str, default: float) -> float:
    """Read a positive floating-point setting from the environment."""
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive number") from error
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return parsed


def _read_int(name: str, default: int, maximum: int | None = None) -> int:
    """Read a positive integer setting from the environment."""
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive integer") from error
    if parsed <= 0 or (maximum is not None and parsed > maximum):
        limit = f" and no more than {maximum}" if maximum is not None else ""
        raise ValueError(f"{name} must be greater than zero{limit}")
    return parsed


@dataclass(frozen=True)
class Settings:
    """Runtime settings shared by all Google API commands."""

    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS
    page_size: int = DEFAULT_PAGE_SIZE
    max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES

    @classmethod
    def from_environment(cls) -> "Settings":
        """Build settings from supported environment variables."""
        return cls(
            timeout_seconds=_read_float(ENV_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS),
            retry_attempts=_read_int(ENV_RETRY_ATTEMPTS, DEFAULT_RETRY_ATTEMPTS),
            max_download_bytes=_read_int(
                ENV_MAX_DOWNLOAD_BYTES,
                DEFAULT_MAX_DOWNLOAD_BYTES,
            ),
        )

    def with_cli_values(
        self,
        page_size: int | None,
        max_download_bytes: int | None,
    ) -> "Settings":
        """Return settings with validated command-line overrides."""
        selected_page_size = self.page_size if page_size is None else page_size
        selected_max_download_bytes = (
            self.max_download_bytes if max_download_bytes is None else max_download_bytes
        )
        if selected_page_size <= 0 or selected_page_size > MAX_PAGE_SIZE:
            raise ValueError(f"page size must be between 1 and {MAX_PAGE_SIZE}")
        if selected_max_download_bytes <= 0:
            raise ValueError("maximum download size must be greater than zero")
        return Settings(
            timeout_seconds=self.timeout_seconds,
            retry_attempts=self.retry_attempts,
            backoff_seconds=self.backoff_seconds,
            page_size=selected_page_size,
            max_download_bytes=selected_max_download_bytes,
        )
