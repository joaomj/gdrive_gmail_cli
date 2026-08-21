"""User-facing Gmail and Drive behavior through a fake HTTP boundary."""

from __future__ import annotations

import base64
from collections.abc import Callable
from pathlib import Path

import httpx

from google_personal_cli.api import GoogleApiClient
from google_personal_cli.config import Settings
from google_personal_cli.drive import download as drive_download
from google_personal_cli.errors import LocalError
from google_personal_cli.gmail import get_message
from google_personal_cli.gmail import search as gmail_search


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> GoogleApiClient:
    """Build a client against a deterministic external HTTP boundary."""
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = Settings(retry_attempts=0)
    return GoogleApiClient("https://example.test/api", None, settings, http_client)


def test_gmail_search_returns_ids_and_pagination() -> None:
    """Gmail search preserves result IDs and the next page token."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/users/me/threads"
        assert request.url.params["q"] == "from:alice@example.com"
        return httpx.Response(
            200,
            json={
                "threads": [{"id": "thread-1", "snippet": "Hello"}],
                "nextPageToken": "next-1",
                "resultSizeEstimate": 1,
            },
            request=request,
        )

    client = _client(handler)
    try:
        result = gmail_search(
            client,
            "from:alice@example.com",
            10,
            None,
            "threads",
            False,
        )
    finally:
        client.close()

    assert result["results"] == [{"id": "thread-1", "snippet": "Hello"}]
    assert result["nextPageToken"] == "next-1"


def test_gmail_message_decodes_plain_text_and_headers() -> None:
    """Message retrieval exposes readable text and stable header fields."""
    encoded = base64.urlsafe_b64encode(b"Hello from Gmail").decode().rstrip("=")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "message-1",
                "threadId": "thread-1",
                "payload": {
                    "mimeType": "multipart/alternative",
                    "headers": [
                        {"name": "Subject", "value": "A subject"},
                        {"name": "From", "value": "alice@example.com"},
                    ],
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {"data": encoded},
                        }
                    ],
                },
            },
            request=request,
        )

    client = _client(handler)
    try:
        result = get_message(client, "message-1", "full")
    finally:
        client.close()

    assert result["subject"] == "A subject"
    assert result["from"] == "alice@example.com"
    assert result["plainText"] == "Hello from Gmail"


def test_drive_download_writes_file_after_capability_check(tmp_path: Path) -> None:
    """Drive download checks metadata before it writes the requested file."""
    output_path = tmp_path / "report.pdf"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/files/file-1") and request.url.params.get("alt") is None:
            return httpx.Response(
                200,
                json={
                    "id": "file-1",
                    "name": "report.pdf",
                    "mimeType": "application/pdf",
                    "capabilities": {"canDownload": True},
                },
                request=request,
            )
        assert request.url.params["alt"] == "media"
        return httpx.Response(200, content=b"pdf bytes", request=request)

    client = _client(handler)
    try:
        result = drive_download(client, "file-1", output_path, 100, False)
    finally:
        client.close()

    assert result["bytes"] == 9
    assert output_path.read_bytes() == b"pdf bytes"


def test_drive_download_does_not_overwrite_without_force(tmp_path: Path) -> None:
    """A local output file remains unchanged unless force is explicit."""
    output_path = tmp_path / "report.pdf"
    output_path.write_bytes(b"original")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "file-1",
                "name": "report.pdf",
                "mimeType": "application/pdf",
                "capabilities": {"canDownload": True},
            },
            request=request,
        )

    client = _client(handler)
    try:
        result: LocalError | None = None
        try:
            drive_download(client, "file-1", output_path, 100, False)
        except LocalError as error:
            result = error
    finally:
        client.close()

    assert result is not None
    assert output_path.read_bytes() == b"original"
