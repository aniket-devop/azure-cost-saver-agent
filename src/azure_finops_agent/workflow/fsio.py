"""Small file helper: UTF-8 bytes (no newline translation), replaced atomically."""

from __future__ import annotations

import os
from pathlib import Path


def write_text_atomic(path: Path, content: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(content.encode("utf-8"))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
