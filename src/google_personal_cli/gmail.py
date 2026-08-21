"""Read-only Gmail API operations."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from pathlib import Path

from google_personal_cli.api import GoogleApiClient
from google_personal_cli.config import (
    GMAIL_ATTACHMENT_PATH_TEMPLATE,
    GMAIL_LABELS_PATH,
    GMAIL_MESSAGE_PATH_TEMPLATE,
    GMAIL_MESSAGES_PATH,
    GMAIL_THREAD_PATH_TEMPLATE,
    GMAIL_THREADS_PATH,
)
from google_personal_cli.errors import ApiError, ValidationError
from google_personal_cli.storage import write_bytes


def _mapping(value: object) -> Mapping[str, object]:
    """Return a response object or an empty object for optional payload fields."""
    if isinstance(value, Mapping):
        return value
    return {}


def _string(value: object, default: str = "") -> str:
    """Read a string field from an untrusted API response."""
    return value if isinstance(value, str) else default


def _objects(value: object) -> list[Mapping[str, object]]:
    """Read a list of response objects and ignore malformed entries."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _decode_body(value: str) -> str:
    """Decode Gmail's URL-safe base64 body representation."""
    try:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding).decode("utf-8", errors="replace")
    except (ValueError, binascii.Error) as error:
        raise ApiError("Gmail returned an invalid message body") from error


def _headers(payload: Mapping[str, object]) -> dict[str, str]:
    """Normalize Gmail header entries into a predictable object."""
    result: dict[str, str] = {}
    for header in _objects(payload.get("headers")):
        name = _string(header.get("name"))
        value = _string(header.get("value"))
        if name:
            result[name] = value
    return result


def _collect_parts(
    part: Mapping[str, object],
    plain_text: list[str],
    html: list[str],
    attachments: list[dict[str, object]],
) -> None:
    """Collect text and attachment metadata from nested MIME parts."""
    body = _mapping(part.get("body"))
    data = body.get("data")
    mime_type = _string(part.get("mimeType"))
    filename = _string(part.get("filename"))
    attachment_id = _string(body.get("attachmentId"))
    if filename and attachment_id:
        attachments.append(
            {
                "attachmentId": attachment_id,
                "filename": filename,
                "mimeType": mime_type,
                "size": body.get("size", 0),
            }
        )
    elif isinstance(data, str) and data:
        decoded = _decode_body(data)
        if mime_type == "text/plain":
            plain_text.append(decoded)
        elif mime_type == "text/html":
            html.append(decoded)
    for child in _objects(part.get("parts")):
        _collect_parts(child, plain_text, html, attachments)


def _normalize_message(message: Mapping[str, object]) -> dict[str, object]:
    """Convert a Gmail message resource into agent-friendly content."""
    payload = _mapping(message.get("payload"))
    plain_text: list[str] = []
    html: list[str] = []
    attachments: list[dict[str, object]] = []
    _collect_parts(payload, plain_text, html, attachments)
    header_values = _headers(payload)
    return {
        "id": _string(message.get("id")),
        "threadId": _string(message.get("threadId")),
        "labelIds": message.get("labelIds", []),
        "internalDate": _string(message.get("internalDate")),
        "headers": header_values,
        "subject": header_values.get("Subject", ""),
        "from": header_values.get("From", ""),
        "to": header_values.get("To", ""),
        "cc": header_values.get("Cc", ""),
        "date": header_values.get("Date", ""),
        "plainText": "\n\n".join(plain_text),
        "html": "\n\n".join(html),
        "attachments": attachments,
        "sizeEstimate": message.get("sizeEstimate", 0),
    }


def _validate_limit(limit: int) -> None:
    """Validate a per-request result limit."""
    if limit <= 0:
        raise ValidationError("limit must be greater than zero")


def search(
    client: GoogleApiClient,
    query: str,
    limit: int,
    page_token: str | None,
    resource: str,
    include_spam_trash: bool,
) -> dict[str, object]:
    """Search Gmail threads or messages using Gmail query syntax."""
    _validate_limit(limit)
    if resource not in {"threads", "messages"}:
        raise ValidationError("resource must be either threads or messages")
    response = client.get_json(
        GMAIL_THREADS_PATH if resource == "threads" else GMAIL_MESSAGES_PATH,
        {
            "q": query,
            "maxResults": limit,
            "pageToken": page_token,
            "includeSpamTrash": include_spam_trash,
        },
        f"Gmail {resource} search",
    )
    key = resource
    return {
        "resource": resource,
        "query": query,
        "results": response.get(key, []),
        "nextPageToken": response.get("nextPageToken"),
        "resultSizeEstimate": response.get("resultSizeEstimate", 0),
    }


def get_thread(client: GoogleApiClient, thread_id: str, message_format: str) -> dict[str, object]:
    """Retrieve and normalize every message in a Gmail thread."""
    if not thread_id:
        raise ValidationError("thread ID must not be empty")
    response = client.get_json(
        GMAIL_THREAD_PATH_TEMPLATE.format(thread_id),
        {"format": message_format},
        "Gmail thread get",
    )
    return {
        "id": _string(response.get("id"), thread_id),
        "historyId": _string(response.get("historyId")),
        "messages": [_normalize_message(item) for item in _objects(response.get("messages"))],
    }


def get_message(client: GoogleApiClient, message_id: str, message_format: str) -> dict[str, object]:
    """Retrieve and normalize one Gmail message."""
    if not message_id:
        raise ValidationError("message ID must not be empty")
    response = client.get_json(
        GMAIL_MESSAGE_PATH_TEMPLATE.format(message_id),
        {"format": message_format},
        "Gmail message get",
    )
    return _normalize_message(response)


def list_labels(client: GoogleApiClient) -> dict[str, object]:
    """List Gmail system and user labels."""
    response = client.get_json(
        GMAIL_LABELS_PATH,
        {},
        "Gmail labels list",
    )
    return {"labels": response.get("labels", [])}


def download_attachment(
    client: GoogleApiClient,
    message_id: str,
    attachment_id: str,
    output_path: Path,
    max_bytes: int,
    force: bool,
) -> dict[str, object]:
    """Download one Gmail attachment through an atomic local write."""
    if not message_id or not attachment_id:
        raise ValidationError("message ID and attachment ID must not be empty")
    response = client.get_json(
        GMAIL_ATTACHMENT_PATH_TEMPLATE.format(message_id, attachment_id),
        {},
        "Gmail attachment get",
    )
    encoded_data = response.get("data")
    if not isinstance(encoded_data, str):
        raise ApiError("Gmail attachment response did not include data")
    try:
        padding = "=" * (-len(encoded_data) % 4)
        content = base64.urlsafe_b64decode(encoded_data + padding)
    except (ValueError, binascii.Error) as error:
        raise ApiError("Gmail returned invalid attachment data") from error
    if len(content) > max_bytes:
        raise ValidationError("attachment exceeds the maximum download size")
    size = write_bytes(output_path, content, force)
    return {
        "messageId": message_id,
        "attachmentId": attachment_id,
        "output": str(output_path),
        "bytes": size,
    }
