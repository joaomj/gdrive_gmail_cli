"""Command-line entry point for read-only Google Personal CLI."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from google_personal_cli import __version__
from google_personal_cli.api import GoogleApiClient
from google_personal_cli.auth import check_authentication, load_credentials, login, revoke
from google_personal_cli.config import (
    DRIVE_API_BASE_URL,
    GMAIL_API_BASE_URL,
    Settings,
)
from google_personal_cli.drive import download as drive_download
from google_personal_cli.drive import export as drive_export
from google_personal_cli.drive import get_file as drive_get_file
from google_personal_cli.drive import search as drive_search
from google_personal_cli.errors import GPersonalError, ValidationError
from google_personal_cli.gmail import download_attachment, get_message, get_thread
from google_personal_cli.gmail import list_labels as gmail_list_labels
from google_personal_cli.gmail import search as gmail_search
from google_personal_cli.output import emit, emit_error


def _positive_integer(value: str) -> int:
    """Parse a positive integer for argparse."""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(
        prog="gpersonal",
        description="Read-only Gmail and Google Drive access for personal automation.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--page-size", type=_positive_integer, default=None)
    parser.add_argument("--max-download-bytes", type=_positive_integer, default=None)
    commands = parser.add_subparsers(dest="command", required=True)

    auth_parser = commands.add_parser("auth", help="manage OAuth credentials")
    auth_commands = auth_parser.add_subparsers(dest="auth_command", required=True)
    login_parser = auth_commands.add_parser("login", help="authorize read-only access")
    login_parser.add_argument("--client-id-file", type=Path, required=True)
    login_parser.add_argument("--no-browser", action="store_true")
    auth_commands.add_parser("status", help="check OAuth status")
    auth_commands.add_parser("revoke", help="revoke OAuth access")

    gmail_parser = commands.add_parser("gmail", help="read Gmail")
    gmail_commands = gmail_parser.add_subparsers(dest="gmail_command", required=True)
    gmail_search_parser = gmail_commands.add_parser("search", help="search Gmail")
    gmail_search_parser.add_argument("--query", required=True)
    gmail_search_parser.add_argument(
        "--resource",
        choices=("threads", "messages"),
        default="threads",
    )
    gmail_search_parser.add_argument("--limit", type=_positive_integer, default=None)
    gmail_search_parser.add_argument("--page-token")
    gmail_search_parser.add_argument("--include-spam-trash", action="store_true")
    for command_name, help_text in (
        ("thread", "access a Gmail thread"),
        ("message", "access a Gmail message"),
    ):
        resource_parser = gmail_commands.add_parser(command_name, help=help_text)
        resource_commands = resource_parser.add_subparsers(
            dest="gmail_resource_command",
            required=True,
        )
        get_parser = resource_commands.add_parser("get", help=f"get a Gmail {command_name}")
        get_parser.add_argument("id")
        get_parser.add_argument(
            "--format",
            choices=("full", "metadata", "minimal", "raw"),
            default="full",
        )
    attachment_parser = gmail_commands.add_parser("attachment", help="access a Gmail attachment")
    attachment_commands = attachment_parser.add_subparsers(
        dest="gmail_resource_command",
        required=True,
    )
    download_attachment_parser = attachment_commands.add_parser(
        "download",
        help="download a Gmail attachment",
    )
    download_attachment_parser.add_argument("message_id")
    download_attachment_parser.add_argument("attachment_id")
    download_attachment_parser.add_argument("--output", type=Path, required=True)
    download_attachment_parser.add_argument("--force", action="store_true")
    labels_parser = gmail_commands.add_parser("labels", help="access Gmail labels")
    labels_commands = labels_parser.add_subparsers(
        dest="gmail_resource_command",
        required=True,
    )
    labels_commands.add_parser("list", help="list Gmail labels")

    drive_parser = commands.add_parser("drive", help="read Google Drive")
    drive_commands = drive_parser.add_subparsers(dest="drive_command", required=True)
    drive_search_parser = drive_commands.add_parser("search", help="search Drive files")
    drive_search_parser.add_argument("--query", required=True)
    drive_search_parser.add_argument("--limit", type=_positive_integer, default=None)
    drive_search_parser.add_argument("--page-token")
    drive_search_parser.add_argument("--order-by")
    drive_search_parser.add_argument("--corpus")
    drive_file_parser = drive_commands.add_parser("file", help="access a Drive file")
    drive_file_commands = drive_file_parser.add_subparsers(
        dest="drive_resource_command",
        required=True,
    )
    drive_get_parser = drive_file_commands.add_parser("get", help="get Drive file metadata")
    drive_get_parser.add_argument("file_id")
    for command_name, help_text in (
        ("download", "download a Drive file"),
        ("export", "export a Workspace file"),
    ):
        download_parser = drive_commands.add_parser(command_name, help=help_text)
        download_parser.add_argument("file_id")
        download_parser.add_argument("--output", type=Path, required=True)
        download_parser.add_argument("--force", action="store_true")
    export_parser = drive_commands.choices["export"]
    export_parser.add_argument("--mime-type", required=True)

    return parser


def _settings(namespace: argparse.Namespace) -> Settings:
    """Load environment configuration and apply CLI overrides."""
    return Settings.from_environment().with_cli_values(
        namespace.page_size,
        namespace.max_download_bytes,
    )


def _run_gmail(namespace: argparse.Namespace, settings: Settings) -> object:
    """Execute one Gmail command with one shared client."""
    credentials, _ = load_credentials()
    client = GoogleApiClient(GMAIL_API_BASE_URL, credentials, settings)
    try:
        if namespace.gmail_command == "search":
            return gmail_search(
                client,
                namespace.query,
                namespace.limit or settings.page_size,
                namespace.page_token,
                namespace.resource,
                namespace.include_spam_trash,
            )
        if namespace.gmail_command == "thread" and namespace.gmail_resource_command == "get":
            return get_thread(client, namespace.id, namespace.format)
        if namespace.gmail_command == "message" and namespace.gmail_resource_command == "get":
            return get_message(client, namespace.id, namespace.format)
        if (
            namespace.gmail_command == "attachment"
            and namespace.gmail_resource_command == "download"
        ):
            return download_attachment(
                client,
                namespace.message_id,
                namespace.attachment_id,
                namespace.output,
                settings.max_download_bytes,
                namespace.force,
            )
        if namespace.gmail_command == "labels" and namespace.gmail_resource_command == "list":
            return gmail_list_labels(client)
        raise ValidationError(f"unknown Gmail command: {namespace.gmail_command}")
    finally:
        client.close()


def _run_drive(namespace: argparse.Namespace, settings: Settings) -> object:
    """Execute one Drive command with one shared client."""
    credentials, _ = load_credentials()
    client = GoogleApiClient(DRIVE_API_BASE_URL, credentials, settings)
    try:
        if namespace.drive_command == "search":
            return drive_search(
                client,
                namespace.query,
                namespace.limit or settings.page_size,
                namespace.page_token,
                namespace.order_by,
                namespace.corpus,
            )
        if namespace.drive_command == "file" and namespace.drive_resource_command == "get":
            return drive_get_file(client, namespace.file_id)
        if namespace.drive_command == "download":
            return drive_download(
                client,
                namespace.file_id,
                namespace.output,
                settings.max_download_bytes,
                namespace.force,
            )
        if namespace.drive_command == "export":
            return drive_export(
                client,
                namespace.file_id,
                namespace.mime_type,
                namespace.output,
                settings.max_download_bytes,
                namespace.force,
            )
        raise ValidationError(f"unknown Drive command: {namespace.drive_command}")
    finally:
        client.close()


def _run(namespace: argparse.Namespace) -> object:
    """Dispatch parsed arguments to the selected service."""
    if namespace.command == "auth":
        if namespace.auth_command == "login":
            login(namespace.client_id_file, namespace.no_browser)
            return {"authenticated": True, "scopes": "gmail.readonly,drive.readonly"}
        if namespace.auth_command == "status":
            return check_authentication()
        if namespace.auth_command == "revoke":
            revoke()
            return {"revoked": True}
        raise ValidationError(f"unknown auth command: {namespace.auth_command}")
    settings = _settings(namespace)
    if namespace.command == "gmail":
        return _run_gmail(namespace, settings)
    if namespace.command == "drive":
        return _run_drive(namespace, settings)
    raise ValidationError(f"unknown command: {namespace.command}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its process exit code."""
    try:
        namespace = _parser().parse_args(argv)
        emit(_run(namespace))
    except GPersonalError as error:
        emit_error(error)
        return int(error.code)
    except (ValueError, OSError) as error:
        emit_error(ValidationError(str(error)))
        return 2
    return 0
