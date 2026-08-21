"""Read-only Google Drive API operations."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from google_personal_cli.api import GoogleApiClient
from google_personal_cli.config import (
    DRIVE_EXPORT_PATH_TEMPLATE,
    DRIVE_FILE_PATH_TEMPLATE,
    MAX_EXPORT_BYTES,
)
from google_personal_cli.errors import NotFoundError, ValidationError

FILE_FIELDS = (
    "id,name,mimeType,size,modifiedTime,createdTime,description,webViewLink,"
    "parents,owners(displayName,emailAddress),capabilities(canDownload,canEdit,canShare),"
    "trashed,driveId,md5Checksum"
)


def _mapping(value: object) -> Mapping[str, object]:
    """Return a response object or an empty object for optional fields."""
    if isinstance(value, Mapping):
        return value
    return {}


def _string(value: object, default: str = "") -> str:
    """Read a string field from an untrusted API response."""
    return value if isinstance(value, str) else default


def _validate_limit(limit: int) -> None:
    """Validate a per-request result limit."""
    if limit <= 0:
        raise ValidationError("limit must be greater than zero")


def search(
    client: GoogleApiClient,
    query: str,
    limit: int,
    page_token: str | None,
    order_by: str | None,
    corpus: str | None,
) -> dict[str, object]:
    """Search Drive files using Drive query syntax."""
    _validate_limit(limit)
    response = client.get_json(
        "files",
        {
            "q": query,
            "pageSize": limit,
            "pageToken": page_token,
            "spaces": "drive",
            "fields": f"nextPageToken,incompleteSearch,files({FILE_FIELDS})",
            "orderBy": order_by,
            "corpora": corpus,
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
        },
        "Drive file search",
    )
    return {
        "query": query,
        "files": response.get("files", []),
        "nextPageToken": response.get("nextPageToken"),
        "incompleteSearch": response.get("incompleteSearch", False),
    }


def get_file(client: GoogleApiClient, file_id: str) -> dict[str, object]:
    """Retrieve metadata and download capabilities for one Drive file."""
    if not file_id:
        raise ValidationError("file ID must not be empty")
    return client.get_json(
        DRIVE_FILE_PATH_TEMPLATE.format(file_id),
        {
            "fields": FILE_FIELDS,
            "supportsAllDrives": True,
        },
        "Drive file get",
    )


def _check_download_capability(metadata: Mapping[str, object], operation: str) -> None:
    """Reject files that Google says this credential cannot download."""
    capabilities = _mapping(metadata.get("capabilities"))
    if capabilities.get("canDownload") is not True:
        raise NotFoundError(f"Drive file cannot be downloaded by this account: {operation}")


def download(
    client: GoogleApiClient,
    file_id: str,
    output_path: Path,
    max_bytes: int,
    force: bool,
) -> dict[str, object]:
    """Download a binary Drive file after checking its capability."""
    metadata = get_file(client, file_id)
    _check_download_capability(metadata, file_id)
    mime_type = _string(metadata.get("mimeType"))
    if mime_type.startswith("application/vnd.google-apps."):
        raise ValidationError(
            "Google Workspace files must use `drive export` with a target MIME type"
        )
    size = client.download_to_path(
        DRIVE_FILE_PATH_TEMPLATE.format(file_id),
        {"alt": "media", "supportsAllDrives": True},
        "Drive file download",
        output_path,
        max_bytes,
        force,
    )
    return {
        "id": file_id,
        "name": _string(metadata.get("name")),
        "mimeType": mime_type,
        "output": str(output_path),
        "bytes": size,
    }


def export(
    client: GoogleApiClient,
    file_id: str,
    mime_type: str,
    output_path: Path,
    max_bytes: int,
    force: bool,
) -> dict[str, object]:
    """Export a Google Workspace file with the documented size guard."""
    if not mime_type:
        raise ValidationError("export MIME type must not be empty")
    metadata = get_file(client, file_id)
    _check_download_capability(metadata, file_id)
    size = client.download_to_path(
        DRIVE_EXPORT_PATH_TEMPLATE.format(file_id),
        {"mimeType": mime_type},
        "Drive file export",
        output_path,
        min(max_bytes, MAX_EXPORT_BYTES),
        force,
    )
    return {
        "id": file_id,
        "name": _string(metadata.get("name")),
        "sourceMimeType": _string(metadata.get("mimeType")),
        "mimeType": mime_type,
        "output": str(output_path),
        "bytes": size,
    }
