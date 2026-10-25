"""Publish complete CSV gzip streams and check their structural integrity."""

from __future__ import annotations

import gzip
import os
import tempfile
from pathlib import Path


def verify_gzip(path: Path) -> bytes:
    # Reading to EOF verifies the compressed stream, CRC and uncompressed length.
    return gzip.decompress(path.read_bytes())


def write_csv(frame, path: Path) -> None:
    payload = frame.to_csv(index=False).encode("utf-8")
    compressed = gzip.compress(payload, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".memo-", delete=False) as stream:
            name = Path(stream.name)
            stream.write(compressed)
            stream.flush()
            os.fsync(stream.fileno())
        if verify_gzip(name) != payload:
            raise OSError("CSV gzip roundtrip failed before publication")
        name.replace(path)
        if verify_gzip(path) != payload:
            raise OSError("CSV gzip roundtrip failed after publication")
    finally:
        if name is not None:
            name.unlink(missing_ok=True)
