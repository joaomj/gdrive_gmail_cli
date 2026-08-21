"""User-visible error types and exit codes."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Stable process exit codes for the CLI."""

    SUCCESS = 0
    INVALID_ARGUMENTS = 2
    AUTHENTICATION = 3
    NOT_FOUND = 4
    TRANSIENT_API = 5
    API = 6
    LOCAL = 7


class GPersonalError(Exception):
    """Base class for expected CLI failures."""

    def __init__(self, message: str, code: ExitCode) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class ValidationError(GPersonalError):
    """Raised when local command input is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.INVALID_ARGUMENTS)


class AuthenticationError(GPersonalError):
    """Raised when OAuth credentials are unavailable or invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.AUTHENTICATION)


class NotFoundError(GPersonalError):
    """Raised when Google cannot find or expose a requested resource."""

    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.NOT_FOUND)


class TransientApiError(GPersonalError):
    """Raised when a retryable Google API or network failure persists."""

    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.TRANSIENT_API)


class ApiError(GPersonalError):
    """Raised when a non-retryable Google API response is invalid or fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.API)


class LocalError(GPersonalError):
    """Raised when a local file, process, or credential operation fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message, ExitCode.LOCAL)
