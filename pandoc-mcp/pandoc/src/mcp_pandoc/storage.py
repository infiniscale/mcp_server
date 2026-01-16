"""MinIO storage integration for converted files."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Optional

try:
    from minio import Minio
    from minio.error import S3Error

    MINIO_AVAILABLE = True
except ImportError:
    MINIO_AVAILABLE = False

from . import config

logger = logging.getLogger(__name__)

_storage_instance: Optional["MinIOStorage"] = None


class MinIOStorage:
    """MinIO storage handler for converted files."""

    def __init__(self) -> None:
        """Initialize MinIO client."""
        if not MINIO_AVAILABLE:
            raise ImportError("minio package not installed. Install with: pip install minio")

        if not config.MINIO_ENABLED:
            raise RuntimeError("MinIO is not enabled in configuration")

        if not config.MINIO_ACCESS_KEY or not config.MINIO_SECRET_KEY:
            raise RuntimeError("MinIO credentials not configured")

        self.client = Minio(
            config.MINIO_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
            secure=config.MINIO_SECURE,
        )
        self.bucket = config.MINIO_BUCKET

        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        """Ensure the bucket exists, create if not."""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info("Created MinIO bucket: %s", self.bucket)
        except S3Error as exc:
            logger.error("Failed to check/create bucket: %s", exc)
            raise

    def upload_file(
        self,
        file_path: Path,
        object_name: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> dict:
        """Upload file to MinIO and return metadata with download URL."""
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not object_name:
            import time

            timestamp = int(time.time())
            object_name = f"{timestamp}_{file_path.name}"

        if not content_type:
            content_type = self._detect_content_type(file_path)

        try:
            self.client.fput_object(
                self.bucket,
                object_name,
                str(file_path),
                content_type=content_type,
            )

            download_url = self.client.presigned_get_object(
                self.bucket,
                object_name,
                expires=timedelta(seconds=config.MINIO_URL_EXPIRY),
            )

            file_size = file_path.stat().st_size

            return {
                "object_name": object_name,
                "download_url": download_url,
                "size": file_size,
                "content_type": content_type,
                "bucket": self.bucket,
            }
        except S3Error as exc:
            logger.error("Failed to upload to MinIO: %s", exc)
            raise

    def _detect_content_type(self, file_path: Path) -> str:
        """Detect MIME type from file extension."""
        ext = file_path.suffix.lower()
        mime_map = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".md": "text/markdown",
            ".markdown": "text/markdown",
            ".html": "text/html",
            ".htm": "text/html",
            ".txt": "text/plain",
            ".rst": "text/plain",
            ".epub": "application/epub+zip",
            ".odt": "application/vnd.oasis.opendocument.text",
            ".tex": "application/x-tex",
            ".ipynb": "application/x-ipynb+json",
        }
        return mime_map.get(ext, "application/octet-stream")


def get_storage() -> Optional[MinIOStorage]:
    """Get MinIO storage instance if enabled."""
    global _storage_instance

    if not config.MINIO_ENABLED:
        return None

    if not MINIO_AVAILABLE:
        logger.warning("MinIO is enabled but minio package is not installed")
        return None

    if _storage_instance is None:
        try:
            _storage_instance = MinIOStorage()
        except Exception as exc:
            logger.error("Failed to initialize MinIO storage: %s", exc)
            return None

    return _storage_instance
