"""Photo ingest adapter for BlueFolder uploads and archive-email handoff."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from email.message import EmailMessage
import importlib
import io
import logging
import os
from pathlib import Path
import smtplib
import sys
from types import TracebackType

from PIL import Image, ImageOps

from ops_hub.models.requests import PhotoArchiveResult, PhotoAttachmentPayload, PhotoIngestMessage, PhotoIngestResult


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PhotoIngestAdapter:
    """Adapter boundary for photo ingest behavior."""

    base_path: str | None = None
    bluefolder_api_path: str | None = None
    bluefolder_api_key: str | None = None
    bluefolder_account_name: str | None = None
    bluefolder_base_url: str | None = None
    bluefolder_host_header: str | None = None
    bluefolder_verify_ssl: bool | None = None
    bluefolder_timeout_seconds: float | None = None
    compress_max_dimension: int = 1800
    compress_jpeg_quality: int = 82
    archive_smtp_host: str | None = None
    archive_smtp_port: int | None = None
    archive_smtp_username: str | None = None
    archive_smtp_password: str | None = None
    archive_smtp_use_tls: bool = True
    archive_from_email: str | None = None
    archive_to_email: str | None = None

    async def healthcheck(self) -> dict[str, str]:
        """Return current photo-ingest integration status."""
        return {
            "status": "configured" if self._resolve_bluefolder_path() else "placeholder",
            "source": "photo_ingest_adapter",
        }

    async def ingest_message(self, message: PhotoIngestMessage) -> PhotoIngestResult:
        """Return a placeholder photo-ingest handling result."""
        if message.attachment_count <= 0:
            return PhotoIngestResult(
                handled=False,
                status="ignored_no_attachments",
                message="Message did not include attachments.",
            )

        return PhotoIngestResult(
            handled=True,
            status="placeholder_ready",
            message="Photo ingest listener received an attachment-bearing message.",
        )

    async def attach_photo_to_service_request(
        self,
        sr_id: int,
        *,
        photo: PhotoAttachmentPayload,
        uploaded_by_user_id: int,
        label: str = "MDLSN",
    ) -> PhotoArchiveResult:
        """Compress and attach a single image to a BlueFolder service request."""
        client = self._build_bluefolder_client()
        if client is None:
            return PhotoArchiveResult(
                ok=False,
                status="client_unconfigured",
                message="BlueFolder client is not configured for photo uploads.",
            )

        try:
            compressed_name, compressed_bytes = self._compress_attachment(photo)
        except Exception as exc:
            logger.warning("Photo compression failed for %s: %s", photo.filename, exc)
            return PhotoArchiveResult(
                ok=False,
                status="compression_failed",
                message=f"Could not compress the uploaded image: {exc}",
            )

        description = f"{label} upload from Discord user {uploaded_by_user_id}"
        try:
            client.attachments.add_to_service_request(
                sr_id,
                compressed_name,
                base64.b64encode(compressed_bytes).decode("ascii"),
                description=description,
            )
        except Exception as exc:
            logger.exception("BlueFolder attachment upload failed for SR %s", sr_id)
            return PhotoArchiveResult(
                ok=False,
                status="upload_failed",
                message=f"Could not attach photo to SR-{sr_id}: {exc}",
            )

        return PhotoArchiveResult(
            ok=True,
            status="uploaded",
            message=(
                f"Attached `{compressed_name}` to `SR-{sr_id}` "
                f"({self._human_file_size(len(compressed_bytes))})."
            ),
        )

    async def archive_photos_via_email(
        self,
        sr_id: int,
        *,
        photos: list[PhotoAttachmentPayload],
        uploaded_by_user_id: int,
        sr_subject: str | None = None,
    ) -> PhotoArchiveResult:
        """Compress and email one or more photos to the configured archive mailbox."""
        if not self._archive_email_configured():
            return PhotoArchiveResult(
                ok=False,
                status="archive_unconfigured",
                message="Archive email is not configured for photo handoff.",
            )
        if not photos:
            return PhotoArchiveResult(
                ok=False,
                status="no_photos",
                message="At least one photo is required for archive handoff.",
            )

        compressed: list[tuple[str, bytes]] = []
        for photo in photos:
            try:
                compressed.append(self._compress_attachment(photo))
            except Exception as exc:
                logger.warning("Photo compression failed for archive handoff %s: %s", photo.filename, exc)
                return PhotoArchiveResult(
                    ok=False,
                    status="compression_failed",
                    message=f"Could not compress `{photo.filename}`: {exc}",
                )

        message = EmailMessage()
        subject = f"SR-{sr_id}"
        if sr_subject:
            subject = f"{subject} {sr_subject}"
        message["Subject"] = subject
        message["From"] = self.archive_from_email
        message["To"] = self.archive_to_email
        message.set_content(
            "\n".join(
                [
                    f"Ops Hub photo archive handoff for SR-{sr_id}",
                    f"Uploaded by Discord user {uploaded_by_user_id}",
                    f"Attachment count: {len(compressed)}",
                ]
            )
        )
        for file_name, file_bytes in compressed:
            message.add_attachment(file_bytes, maintype="image", subtype="jpeg", filename=file_name)

        try:
            with smtplib.SMTP(self.archive_smtp_host, self.archive_smtp_port, timeout=30) as smtp:
                if self.archive_smtp_use_tls:
                    smtp.starttls()
                if self.archive_smtp_username:
                    smtp.login(self.archive_smtp_username, self.archive_smtp_password or "")
                smtp.send_message(message)
        except Exception as exc:
            logger.exception("Photo archive email handoff failed for SR %s", sr_id)
            return PhotoArchiveResult(
                ok=False,
                status="archive_send_failed",
                message=f"Could not send archive email for SR-{sr_id}: {exc}",
            )

        return PhotoArchiveResult(
            ok=True,
            status="archived",
            message=f"Emailed `{len(compressed)}` compressed photo(s) for `SR-{sr_id}` to the archive mailbox.",
        )

    def _archive_email_configured(self) -> bool:
        """Return whether archive email settings are configured."""
        return bool(
            (self.archive_smtp_host or "").strip()
            and self.archive_smtp_port
            and (self.archive_from_email or "").strip()
            and (self.archive_to_email or "").strip()
        )

    def _compress_attachment(self, photo: PhotoAttachmentPayload) -> tuple[str, bytes]:
        """Compress an uploaded photo into a normalized JPEG payload."""
        with Image.open(io.BytesIO(photo.data)) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode not in ("RGB", "L"):
                flattened = Image.new("RGB", image.size, (255, 255, 255))
                flattened.paste(image.convert("RGBA"), mask=image.convert("RGBA").split()[-1])
                image = flattened
            elif image.mode == "L":
                image = image.convert("RGB")

            image.thumbnail((self.compress_max_dimension, self.compress_max_dimension))
            output = io.BytesIO()
            image.save(
                output,
                format="JPEG",
                optimize=True,
                quality=self.compress_jpeg_quality,
            )
            stem = Path(photo.filename).stem or "photo"
            return f"{stem}.jpg", output.getvalue()

    def _build_bluefolder_client(self) -> object | None:
        """Construct a BlueFolder client for attachment operations."""
        resolved_path = self._resolve_bluefolder_path()
        if resolved_path is None or not resolved_path.exists():
            return None
        if not (self.bluefolder_api_key or "").strip():
            return None
        if not ((self.bluefolder_account_name or "").strip() or (self.bluefolder_base_url or "").strip()):
            return None

        try:
            with _temporary_sys_path(resolved_path), _temporary_bluefolder_env(
                api_key=self.bluefolder_api_key,
                account_name=self.bluefolder_account_name,
                base_url=self.bluefolder_base_url,
                host_header=self.bluefolder_host_header,
                verify_ssl=self.bluefolder_verify_ssl,
                timeout_seconds=self.bluefolder_timeout_seconds,
            ):
                importlib.invalidate_caches()
                sys.modules.pop("bluefolder_api", None)
                sys.modules.pop("bluefolder_api.client", None)
                module = importlib.import_module("bluefolder_api.client")
                client_class = getattr(module, "BlueFolderClient")
                return client_class(base_url=(self.bluefolder_base_url or None))
        except Exception:
            logger.exception("Failed to build BlueFolder client for photo ingest")
            return None

    def _resolve_bluefolder_path(self) -> Path | None:
        """Resolve the configured BlueFolder library path."""
        return Path(self.bluefolder_api_path).expanduser() if self.bluefolder_api_path else None

    @staticmethod
    def _human_file_size(size_bytes: int) -> str:
        """Render a compact file-size string."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        return f"{size_bytes / (1024 * 1024):.1f} MB"


class _temporary_sys_path:
    """Context manager that temporarily prepends a path to ``sys.path``."""

    def __init__(self, path: Path) -> None:
        self.path = str(path)

    def __enter__(self) -> None:
        if self.path not in sys.path:
            sys.path.insert(0, self.path)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            sys.path.remove(self.path)
        except ValueError:
            pass


class _temporary_bluefolder_env:
    """Context manager for configuring the shared BlueFolder client safely."""

    def __init__(
        self,
        *,
        api_key: str | None,
        account_name: str | None,
        base_url: str | None,
        host_header: str | None,
        verify_ssl: bool | None,
        timeout_seconds: float | None,
    ) -> None:
        self.values = {
            "BLUEFOLDER_API_KEY": api_key or "",
            "BLUEFOLDER_ACCOUNT_NAME": account_name or "",
            "BLUEFOLDER_BASE_URL": base_url or "",
            "BLUEFOLDER_HOST_HEADER": host_header or "",
            "BLUEFOLDER_VERIFY_SSL": "" if verify_ssl is None else str(verify_ssl).lower(),
            "BLUEFOLDER_TIMEOUT_SECONDS": "" if timeout_seconds is None else str(timeout_seconds),
        }
        self.previous: dict[str, str | None] = {}

    def __enter__(self) -> None:
        for key, value in self.values.items():
            self.previous[key] = os.environ.get(key)
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        for key, previous_value in self.previous.items():
            if previous_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous_value
