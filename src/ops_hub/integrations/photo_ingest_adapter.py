"""Photo ingest adapter for BlueFolder uploads and archive-email handoff."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from email.message import EmailMessage
from email import message_from_bytes
from email.header import decode_header, make_header
import io
import imaplib
import logging
import os
from pathlib import Path
import re
import smtplib
from types import TracebackType
from datetime import datetime, timedelta

from PIL import Image, ImageOps

from ops_hub.integrations.import_context import TemporarySysPath, import_module_from_path
from ops_hub.models.requests import (
    ArchivedPhotoRecord,
    PhotoArchiveResult,
    PhotoAttachmentPayload,
    PhotoComplianceSummary,
    PhotoIngestMessage,
    PhotoIngestResult,
)


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
    compress_max_mb: int = 5
    archive_smtp_host: str | None = None
    archive_smtp_port: int | None = None
    archive_smtp_username: str | None = None
    archive_smtp_password: str | None = None
    archive_smtp_use_tls: bool = True
    archive_from_email: str | None = None
    archive_to_email: str | None = None
    mailbox_imap_host: str | None = None
    mailbox_imap_port: int | None = None
    mailbox_imap_username: str | None = None
    mailbox_imap_password: str | None = None
    mailbox_imap_use_ssl: bool = True
    mailbox_folder: str = "INBOX"
    mailbox_search_days: int = 21
    required_tags: tuple[str, ...] = ("model", "serial")

    async def healthcheck(self) -> dict[str, str]:
        """Return current photo-ingest integration status."""
        upload_ready = self._bluefolder_upload_configured()
        archive_ready = self._archive_email_configured()
        mailbox_ready = self._mailbox_scan_configured()
        listener_mode = "full" if archive_ready else "upload_only" if upload_ready else "dormant"
        if archive_ready or mailbox_ready:
            status = "partial" if not (upload_ready and archive_ready and mailbox_ready) else "ready"
        elif upload_ready:
            status = "upload_only"
        else:
            status = "unconfigured"
        return {
            "status": status,
            "source": "photo_ingest_adapter",
            "mode": listener_mode,
            "upload": "configured" if upload_ready else "unconfigured",
            "archive": "configured" if archive_ready else "unconfigured",
            "mailbox": "configured" if mailbox_ready else "unconfigured",
        }

    async def ingest_message(self, message: PhotoIngestMessage) -> PhotoIngestResult:
        """Process a Discord listener message into an archive-email handoff when possible."""
        if message.attachment_count <= 0:
            return PhotoIngestResult(
                handled=False,
                status="ignored_no_attachments",
                message="Message did not include attachments.",
            )

        if not message.attachments:
            return PhotoIngestResult(
                handled=False,
                status="ignored_non_image_attachments",
                message="Message did not include supported image attachments.",
            )

        sr_id_text = self._extract_service_request_id(message.content)
        if sr_id_text is None:
            return PhotoIngestResult(
                handled=False,
                status="missing_sr_reference",
                message="Message must include an SR reference like `SR-12345` to archive photos.",
            )

        if not self._archive_email_configured():
            return PhotoIngestResult(
                handled=False,
                status="archive_unconfigured",
                message="Archive email is not configured for Discord photo-ingest handoff.",
            )

        result = await self.archive_photos_via_email(
            int(sr_id_text),
            photos=message.attachments,
            uploaded_by_user_id=message.author_id,
            uploaded_by_label=message.author_label,
            sr_subject=message.content.strip() or None,
        )
        return PhotoIngestResult(
            handled=result.ok,
            status=result.status,
            message=result.message,
        )

    async def attach_photo_to_service_request(
        self,
        sr_id: int,
        *,
        photo: PhotoAttachmentPayload,
        uploaded_by_user_id: int,
        uploaded_by_label: str | None = None,
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

        uploaded_by = self._uploaded_by_text(uploaded_by_label, uploaded_by_user_id)
        description = f"{label} upload from {uploaded_by}"
        try:
            client.attachments.add_to_service_request(
                sr_id,
                compressed_name,
                base64.b64encode(compressed_bytes).decode("ascii"),
                description=description,
                content_type="image/jpeg",
            )
        except Exception as exc:
            logger.exception("BlueFolder attachment upload failed for SR %s", sr_id)
            return PhotoArchiveResult(
                ok=False,
                status="upload_failed",
                message=f"Could not attach photo to SR-{sr_id}: {exc}",
            )

        logger.info(
            "BlueFolder photo attached",
            extra={
                "sr_id": sr_id,
                "status": "uploaded",
            },
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
        uploaded_by_label: str | None = None,
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

        uploaded_by = self._uploaded_by_text(uploaded_by_label, uploaded_by_user_id)
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
                    f"Uploaded by {uploaded_by}",
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

        logger.info(
            "Photo archive email sent",
            extra={
                "sr_id": sr_id,
                "status": "archived",
            },
        )

        return PhotoArchiveResult(
            ok=True,
            status="archived",
            message=f"Emailed `{len(compressed)}` compressed photo(s) for `SR-{sr_id}` to the archive mailbox.",
        )

    def _uploaded_by_text(self, uploaded_by_label: str | None, uploaded_by_user_id: int) -> str:
        """Return a readable uploader label for BlueFolder notes and archive emails."""
        text = (uploaded_by_label or "").strip()
        if text:
            return text
        return f"Discord user {uploaded_by_user_id}"

    async def get_photo_compliance_summary(self, sr_id: int) -> PhotoComplianceSummary:
        """Read mailbox records whose subject matches the service-request id."""
        if not self._mailbox_scan_configured():
            return PhotoComplianceSummary(
                sr_id=sr_id,
                mailbox_status="unconfigured",
                message="Mailbox scan is not configured for photo compliance yet.",
                matched_records=[],
                total_photos=0,
                found_tags=[],
                missing_tags=[],
            )

        records: list[ArchivedPhotoRecord] = []
        try:
            mailbox = self._open_mailbox()
            criteria = self._build_mailbox_search_criteria(sr_id)
            try:
                mailbox.select(self.mailbox_folder)
                search_status, data = mailbox.search(None, *criteria)
                if search_status != "OK":
                    return PhotoComplianceSummary(
                        sr_id=sr_id,
                        mailbox_status="lookup_failed",
                        message="Mailbox search failed for photo compliance.",
                        matched_records=[],
                        total_photos=0,
                        found_tags=[],
                        missing_tags=[],
                    )
                for message_id in data[0].split():
                    fetch_status, message_data = mailbox.fetch(message_id, "(RFC822)")
                    if fetch_status != "OK":
                        continue
                    for part in message_data:
                        if not isinstance(part, tuple):
                            continue
                        parsed = message_from_bytes(part[1])
                        subject = str(make_header(decode_header(parsed.get("Subject", ""))))
                        if self._extract_service_request_id(subject) != str(sr_id):
                            continue
                        attachment_names = self._image_attachment_names(parsed)
                        attachment_count = len(attachment_names)
                        if attachment_count <= 0:
                            continue
                        records.append(
                            ArchivedPhotoRecord(
                                subject=subject,
                                from_email=parsed.get("From"),
                                received_at=parsed.get("Date"),
                                attachment_count=attachment_count,
                                attachment_names=attachment_names,
                            )
                        )
            finally:
                try:
                    mailbox.close()
                except Exception:
                    pass
                mailbox.logout()
        except Exception as exc:
            logger.exception("Photo mailbox lookup failed for SR %s", sr_id)
            return PhotoComplianceSummary(
                sr_id=sr_id,
                mailbox_status="lookup_failed",
                message=f"Mailbox lookup failed: {exc}",
                matched_records=[],
                total_photos=0,
                found_tags=[],
                missing_tags=[],
            )

        records.sort(key=lambda record: record.received_at or "", reverse=True)
        total_photos = sum(record.attachment_count for record in records)
        found_tags = self._extract_found_tags(records)
        missing_tags = self._missing_required_tags(found_tags)
        if not records:
            return PhotoComplianceSummary(
                sr_id=sr_id,
                mailbox_status="missing",
                message=f"No archived photo email was found for SR-{sr_id}.",
                matched_records=[],
                total_photos=0,
                found_tags=[],
                missing_tags=list(self.required_tags),
            )
        return PhotoComplianceSummary(
            sr_id=sr_id,
            mailbox_status="present",
            message=f"Found `{len(records)}` matching email(s) with `{total_photos}` photo attachment(s) for SR-{sr_id}.",
            matched_records=records,
            total_photos=total_photos,
            found_tags=found_tags,
            missing_tags=missing_tags,
        )

    def _archive_email_configured(self) -> bool:
        """Return whether archive email settings are configured."""
        return bool(
            (self.archive_smtp_host or "").strip()
            and self.archive_smtp_port
            and (self.archive_from_email or "").strip()
            and (self.archive_to_email or "").strip()
        )

    def _bluefolder_upload_configured(self) -> bool:
        """Return whether BlueFolder upload prerequisites are configured."""
        resolved_path = self._resolve_bluefolder_path()
        return bool(
            resolved_path
            and resolved_path.exists()
            and (self.bluefolder_api_key or "").strip()
            and ((self.bluefolder_account_name or "").strip() or (self.bluefolder_base_url or "").strip())
        )

    def _mailbox_scan_configured(self) -> bool:
        """Return whether mailbox scan settings are configured."""
        return bool(
            (self.mailbox_imap_host or "").strip()
            and self.mailbox_imap_port
            and (self.mailbox_imap_username or "").strip()
            and (self.mailbox_imap_password or "").strip()
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
            jpeg_bytes = self._encode_jpeg(image)
            stem = Path(photo.filename).stem or "photo"
            return f"{stem}.jpg", jpeg_bytes

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
            with TemporarySysPath(resolved_path), _temporary_bluefolder_env(
                api_key=self.bluefolder_api_key,
                account_name=self.bluefolder_account_name,
                base_url=self.bluefolder_base_url,
                host_header=self.bluefolder_host_header,
                verify_ssl=self.bluefolder_verify_ssl,
                timeout_seconds=self.bluefolder_timeout_seconds,
            ):
                module = import_module_from_path(
                    "bluefolder_api.client",
                    resolved_path,
                    reset_packages=("bluefolder_api",),
                )
                client_class = getattr(module, "BlueFolderClient")
                return client_class(base_url=(self.bluefolder_base_url or None))
        except (AttributeError, ImportError, ModuleNotFoundError, OSError, TypeError, ValueError):
            logger.exception("Failed to build BlueFolder client for photo ingest")
            return None

    def _open_mailbox(self):
        """Open an IMAP connection for mailbox scans."""
        if self.mailbox_imap_use_ssl:
            mailbox = imaplib.IMAP4_SSL(self.mailbox_imap_host, self.mailbox_imap_port)
        else:
            mailbox = imaplib.IMAP4(self.mailbox_imap_host, self.mailbox_imap_port)
        mailbox.login(self.mailbox_imap_username, self.mailbox_imap_password or "")
        return mailbox

    def _build_mailbox_search_criteria(self, sr_id: int) -> tuple[str, ...]:
        """Build an IMAP search window for recent SR photo mail."""
        since_date = (datetime.now() - timedelta(days=self.mailbox_search_days)).strftime("%d-%b-%Y")
        return ("SINCE", since_date)

    @staticmethod
    def _image_attachment_names(message) -> list[str]:
        """Return image attachment filenames from an email message."""
        names: list[str] = []
        for part in message.walk():
            if part.get_content_maintype() != "image":
                continue
            filename = part.get_filename()
            if not filename:
                continue
            names.append(filename)
        return names

    def _encode_jpeg(self, image: Image.Image) -> bytes:
        """Encode a JPEG while stepping down quality toward the target size."""
        max_bytes = self.compress_max_mb * 1024 * 1024
        qualities: list[int] = []
        for quality in [self.compress_jpeg_quality, 85, 75, 65, 55, 45, 35, 25]:
            if quality not in qualities:
                qualities.append(quality)

        best = b""
        for quality in qualities:
            output = io.BytesIO()
            image.save(output, format="JPEG", optimize=True, quality=quality)
            data = output.getvalue()
            best = data
            if len(data) <= max_bytes:
                break
        return best

    @staticmethod
    def _extract_service_request_id(subject: str | None) -> str | None:
        """Extract the first 4+ digit SR id from a subject line."""
        if not subject:
            return None
        match = re.search(r"(\d{4,})", subject)
        return match.group(1) if match else None

    def _extract_found_tags(self, records: list[ArchivedPhotoRecord]) -> list[str]:
        """Return normalized required tags found in attachment filenames."""
        found: list[str] = []
        normalized_required = [self._normalize_tag(tag) for tag in self.required_tags]
        for record in records:
            for attachment_name in record.attachment_names:
                normalized_name = self._normalize_tag(attachment_name)
                for original_tag, normalized_tag in zip(self.required_tags, normalized_required):
                    if normalized_tag in normalized_name and original_tag not in found:
                        found.append(original_tag)
        return found

    def _missing_required_tags(self, found_tags: list[str]) -> list[str]:
        """Return configured required tags that are still missing."""
        return [tag for tag in self.required_tags if tag not in found_tags]

    @staticmethod
    def _normalize_tag(value: str) -> str:
        """Normalize text for loose tag matching."""
        return value.casefold().replace(" ", "").replace("_", "")

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
