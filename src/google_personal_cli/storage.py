"""Safe local file writes for downloaded Google content."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from google_personal_cli.errors import LocalError


def write_bytes(path: Path, content: bytes, force: bool) -> int:
    """Write bytes atomically without overwriting by default."""
    if path.exists() and not force:
        raise LocalError(f"output file already exists: {path}")
    if not path.parent.exists():
        raise LocalError(f"output directory does not exist: {path.parent}")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
        os.replace(temporary_path, path)
        return len(content)
    except OSError as error:
        raise LocalError(f"could not write {path}") from error
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
