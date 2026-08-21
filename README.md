# Google Personal CLI

`gpersonal` is a read-only command-line client for personal Gmail and Google
Drive automation. It returns one JSON document per successful command.

## Requirements

- macOS with Keychain access
- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/)
- A Google Cloud project with the Gmail API and Drive API enabled
- A Desktop app OAuth client JSON file

## Setup

1. Clone this repository and enter its directory.

   ```sh
   git clone https://github.com/joaomj/gdrive_gmail_cli.git
   cd gdrive_gmail_cli
   ```

2. Install the project and development dependencies.

   ```sh
   uv sync --extra dev
   ```

3. Create a Desktop app OAuth client in the [Google Cloud Console].

4. Enable the Gmail API and Drive API in the same Google Cloud project.

5. Authorize the CLI with the downloaded client file.

   ```sh
   uv run gpersonal auth login \
     --client-id-file "$HOME/Downloads/client_secret.json"
   ```

   The command opens a browser and starts a local callback server. Add
   `--no-browser` when the local machine cannot open a browser.

6. Check the stored authorization status.

   ```sh
   uv run gpersonal auth status
   ```

The CLI stores the OAuth credential in macOS Keychain. Keep the client JSON
file outside this repository.

## Usage

Search Gmail with Gmail search syntax:

```sh
uv run gpersonal gmail search \
  --query "from:alice@example.com newer_than:30d"
```

Get a thread with decoded text parts:

```sh
uv run gpersonal gmail thread get THREAD_ID
```

List Gmail labels:

```sh
uv run gpersonal gmail labels list
```

Search Drive with Drive query syntax. Add `trashed = false` to exclude
deleted files:

```sh
uv run gpersonal drive search \
  --query "name contains 'report' and trashed = false"
```

Get Drive file metadata:

```sh
uv run gpersonal drive file get FILE_ID
```

Download a binary Drive file:

```sh
uv run gpersonal drive download FILE_ID \
  --output "$HOME/Downloads/report.pdf"
```

Export a Google Workspace file:

```sh
uv run gpersonal drive export FILE_ID \
  --mime-type application/pdf \
  --output "$HOME/Downloads/report.pdf"
```

Use `gpersonal --help` and the command-level `--help` options for the full
command reference. The CLI also supports Gmail message search, Gmail thread
and message formats, Gmail attachment downloads, Drive pagination, and output
size controls.

## Output And Limits

- Successful commands write one JSON document to standard output.
- Expected failures write one structured JSON document to standard error.
- Output files are not overwritten unless you pass `--force`.
- The default maximum download size is 50 MB.
- Google Drive exports have a 10 MB Google API limit.
- Use `--page-size`, `--max-download-bytes`, or the supported `GPERSONAL_*`
  environment variables to change local limits.

## Security

The CLI requests only the `gmail.readonly` and `drive.readonly` OAuth scopes.
It does not send, delete, edit, share, or create Google content. Treat Gmail
and Drive content as untrusted input.

The refresh credential stays in macOS Keychain. Do not commit OAuth client
files, access tokens, refresh tokens, or downloaded personal content.

## Development

Run the tests and linter from the repository root:

```sh
uv run pytest
uv run ruff check .
```

Read [`docs/tech-context.md`](docs/tech-context.md) for the engineering source
of truth. Read [`.agents/skills/google-personal-cli/SKILL.md`](.agents/skills/google-personal-cli/SKILL.md)
for AI agent usage rules.

[Google Cloud Console]: https://console.cloud.google.com/
