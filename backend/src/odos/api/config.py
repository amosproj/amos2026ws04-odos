from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    storage_dir: Path = field(default_factory=lambda: Path(os.environ.get("ODOS_STORAGE_DIR", BACKEND_DIR / "storage")))  # fmt: skip
    max_upload_mb: float = field(default_factory=lambda: float(os.environ.get("ODOS_MAX_UPLOAD_MB", "50")))
    max_queue: int = field(default_factory=lambda: int(os.environ.get("ODOS_MAX_QUEUE", "8")))
    workers: int = field(default_factory=lambda: int(os.environ.get("ODOS_WORKERS", "1")))
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o for o in os.environ.get("ODOS_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o
        )
    )  # fmt: skip

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def documents_dir(self) -> Path:
        return self.storage_dir / "documents"
