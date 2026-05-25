from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

from app.core.config import Settings, get_settings


@dataclass(slots=True)
class StoredFile:
    backend: str
    relative_path: str
    absolute_path: Path
    filename: str
    size_bytes: int
    checksum_sha256: str


class LocalDocumentStorage:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def save_upload(self, *, document_id: str, filename: str, content: bytes) -> StoredFile:
        safe_name = self._safe_filename(filename)
        relative_path = Path("documents") / document_id / "original" / safe_name
        absolute_path = self._settings.uploads_dir / relative_path
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_bytes(content)
        return StoredFile(
            backend="local",
            relative_path=relative_path.as_posix(),
            absolute_path=absolute_path,
            filename=safe_name,
            size_bytes=len(content),
            checksum_sha256=sha256(content).hexdigest(),
        )

    def resolve_path(self, relative_path: str) -> Path:
        return (self._settings.uploads_dir / relative_path).resolve()

    def exists(self, relative_path: str) -> bool:
        return self.resolve_path(relative_path).exists()

    def _safe_filename(self, filename: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name)
        return cleaned or "upload.bin"
