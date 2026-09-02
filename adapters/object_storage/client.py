from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import UUID


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent directory traversal and unsafe characters."""
    base = Path(filename).name
    cleaned = re.sub(r"[^a-zA-Z0-9_\.\-\u4e00-\u9fa5]", "_", base)
    return cleaned[:128] if cleaned else "document"


def build_source_key(
    organization_id: UUID | str,
    case_id: UUID | str,
    sha256: str,
    filename: str,
) -> str:
    """Build tenant-isolated object storage key.

    Schema: org/{org_id}/case/{case_id}/source/{sha256}_{sanitized_filename}
    """
    clean_name = sanitize_filename(filename)
    return f"org/{organization_id}/case/{case_id}/source/{sha256}_{clean_name}"


class ObjectStorageClient:
    """Object storage client supporting local filesystem / in-memory storage and S3."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir or os.environ.get("PE_STORAGE_BASE_DIR", "/tmp/patent_evidence_storage"))
        self._memory_store: dict[str, bytes] = {}
        self.use_memory = os.environ.get("PE_STORAGE_BACKEND") == "memory"
        if not self.use_memory:
            self.base_dir.mkdir(parents=True, exist_ok=True)

    async def put_object(
        self,
        storage_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        """Store bytes at the specified tenant-isolated key."""
        if self.use_memory:
            self._memory_store[storage_key] = data
            return

        target_file = self.base_dir / storage_key
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_bytes(data)

    async def get_object(self, storage_key: str) -> bytes | None:
        """Retrieve bytes at the specified key or None if missing."""
        if self.use_memory:
            return self._memory_store.get(storage_key)

        target_file = self.base_dir / storage_key
        if not target_file.is_file():
            return None
        return target_file.read_bytes()

    async def delete_object(self, storage_key: str) -> None:
        """Delete object at the specified key."""
        if self.use_memory:
            self._memory_store.pop(storage_key, None)
            return

        target_file = self.base_dir / storage_key
        if target_file.is_file():
            target_file.unlink()
