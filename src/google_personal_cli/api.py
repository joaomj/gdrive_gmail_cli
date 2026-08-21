"""Authenticated, bounded HTTP access to Google Workspace REST APIs."""

from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path

import httpx
from google.auth.credentials import Credentials
from google.auth.transport.requests import Request

from google_personal_cli.config import (
    DOWNLOAD_CHUNK_BYTES,
    RETRYABLE_HTTP_STATUS_CODES,
    URL_PATH_SEPARATOR,
    Settings,
)
from google_personal_cli.errors import (
    ApiError,
    LocalError,
    NotFoundError,
    TransientApiError,
)


def _json_object(value: object, operation: str) -> dict[str, object]:
    """Validate a Google JSON response at the transport boundary."""
    if not isinstance(value, dict):
        raise ApiError(f"{operation} returned a non-object JSON response")
    return value


def _retry_delay(response: httpx.Response, attempt: int, settings: Settings) -> float:
    """Calculate a bounded retry delay from Google or local defaults."""
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return min(float(retry_after), settings.timeout_seconds)
        except ValueError:
            pass
    return settings.backoff_seconds * (2**attempt)


def _error_detail(response: httpx.Response) -> str:
    """Extract a short, non-secret error description."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(payload, Mapping):
        error_value = payload.get("error")
        if isinstance(error_value, Mapping):
            message = error_value.get("message")
            if isinstance(message, str):
                return message[:500]
        message = payload.get("message")
        if isinstance(message, str):
            return message[:500]
    return "Google API returned an error"


class GoogleApiClient:
    """Small synchronous client shared by Gmail and Drive commands."""

    def __init__(
        self,
        base_url: str,
        credentials: Credentials | None,
        settings: Settings,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip(URL_PATH_SEPARATOR)
        self.credentials = credentials
        self.settings = settings
        self.http_client = http_client or httpx.Client(timeout=settings.timeout_seconds)

    def _headers(self, method: str, url: str) -> dict[str, str]:
        """Create request headers and let google-auth refresh OAuth credentials."""
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.credentials is not None:
            self.credentials.before_request(Request(), method, url, headers)
        return headers

    def _response_error(self, response: httpx.Response, operation: str) -> None:
        """Raise the correct expected error for a failed response."""
        detail = _error_detail(response)
        message = f"{operation} failed with HTTP {response.status_code}: {detail}"
        if response.status_code == 404:
            raise NotFoundError(message)
        if response.status_code in RETRYABLE_HTTP_STATUS_CODES:
            raise TransientApiError(message)
        raise ApiError(message)

    def get_json(
        self,
        path: str,
        params: Mapping[str, str | int | bool | None],
        operation: str,
    ) -> dict[str, object]:
        """Perform a bounded authenticated GET and return a JSON object."""
        url = f"{self.base_url}{URL_PATH_SEPARATOR}{path.lstrip(URL_PATH_SEPARATOR)}"
        clean_params = {key: value for key, value in params.items() if value is not None}
        for attempt in range(self.settings.retry_attempts + 1):
            try:
                response = self.http_client.get(
                    url,
                    params=clean_params,
                    headers=self._headers("GET", url),
                )
            except httpx.TimeoutException as error:
                if attempt < self.settings.retry_attempts:
                    time.sleep(self.settings.backoff_seconds * (2**attempt))
                    continue
                raise TransientApiError(f"{operation} timed out") from error
            except httpx.RequestError as error:
                if attempt < self.settings.retry_attempts:
                    time.sleep(self.settings.backoff_seconds * (2**attempt))
                    continue
                raise TransientApiError(f"{operation} could not reach Google") from error
            if (
                response.status_code in RETRYABLE_HTTP_STATUS_CODES
                and attempt < self.settings.retry_attempts
            ):
                time.sleep(_retry_delay(response, attempt, self.settings))
                continue
            if response.is_error:
                self._response_error(response, operation)
            try:
                payload = response.json()
            except ValueError as error:
                raise ApiError(f"{operation} returned invalid JSON") from error
            return _json_object(payload, operation)
        raise TransientApiError(f"{operation} failed after retries")

    def download_to_path(
        self,
        path: str,
        params: Mapping[str, str | int | bool | None],
        operation: str,
        output_path: Path,
        max_bytes: int,
        force: bool,
    ) -> int:
        """Stream a response into an atomic local file."""
        if output_path.exists() and not force:
            raise LocalError(f"output file already exists: {output_path}")
        if not output_path.parent.exists():
            raise LocalError(f"output directory does not exist: {output_path.parent}")
        url = f"{self.base_url}{URL_PATH_SEPARATOR}{path.lstrip(URL_PATH_SEPARATOR)}"
        clean_params = {key: value for key, value in params.items() if value is not None}
        temporary_path: Path | None = None
        try:
            with self.http_client.stream(
                "GET",
                url,
                params=clean_params,
                headers=self._headers("GET", url),
            ) as response:
                if response.is_error:
                    self._response_error(response, operation)
                content_length = response.headers.get("Content-Length")
                if content_length is not None and int(content_length) > max_bytes:
                    raise LocalError(f"{operation} exceeds the maximum download size")
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=output_path.parent,
                    prefix=f".{output_path.name}.",
                    delete=False,
                ) as temporary_file:
                    temporary_path = Path(temporary_file.name)
                    total_bytes = 0
                    for chunk in response.iter_bytes(DOWNLOAD_CHUNK_BYTES):
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            raise LocalError(f"{operation} exceeds the maximum download size")
                        temporary_file.write(chunk)
            os.replace(temporary_path, output_path)
            return total_bytes
        except httpx.TimeoutException as error:
            raise TransientApiError(f"{operation} timed out") from error
        except httpx.RequestError as error:
            raise TransientApiError(f"{operation} could not reach Google") from error
        except OSError as error:
            raise LocalError(f"could not write {output_path}") from error
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self.http_client.close()
