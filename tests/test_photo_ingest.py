"""Photo ingest listener tests for Ops Hub."""

import asyncio
import base64
import io
from email.message import EmailMessage
import textwrap
from pathlib import Path

from PIL import Image

from ops_hub.core.config import Settings
from ops_hub.models.requests import BlueFolderJobSummary, CommandResult
from ops_hub.integrations.photo_ingest_adapter import PhotoIngestAdapter
from ops_hub.models.requests import PhotoAttachmentPayload, PhotoIngestMessage
from ops_hub.services.photo_feature_flags import PhotoFeatureFlagsService
from ops_hub.services.photo_feature_store import PhotoFeatureStore
from ops_hub.services.photo_ingest import PhotoIngestService


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "discord_token": "token",
        "guild_id": None,
        "log_level": "INFO",
        "environment": "dev",
        "photo_ingest_channel_id": 123,
        "bluefolder_api_path": None,
        "bluebot_discord_extension_path": None,
        "photo_ingest_project_path": None,
        "parts_cannon_project_path": None,
        "dispatch_project_path": None,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _feature_flags(**defaults: bool) -> PhotoFeatureFlagsService:
    return PhotoFeatureFlagsService(
        defaults={
            "mdlsn_upload": defaults.get("mdlsn_upload", True),
            "photo_archive_handoff": defaults.get("photo_archive_handoff", True),
            "photo_mailbox_scan": defaults.get("photo_mailbox_scan", False),
            "weekly_missing_photo_notices": defaults.get("weekly_missing_photo_notices", False),
        },
        store=PhotoFeatureStore(),
    )


def test_photo_ingest_service_ignores_unconfigured_channel() -> None:
    service = PhotoIngestService(
        settings=_settings(photo_ingest_channel_id=None),
        adapter=PhotoIngestAdapter(base_path=None),
        feature_flags=_feature_flags(),
    )

    result = asyncio.run(
        service.handle_message(
            PhotoIngestMessage(
                channel_id=123,
                message_id=1,
                author_id=42,
                content="hello",
                attachment_count=1,
            )
        )
    )

    assert result.handled is False
    assert result.status == "ignored_channel"


def test_photo_ingest_service_ignores_other_channels() -> None:
    service = PhotoIngestService(
        settings=_settings(photo_ingest_channel_id=999),
        adapter=PhotoIngestAdapter(base_path=None),
        feature_flags=_feature_flags(),
    )

    result = asyncio.run(
        service.handle_message(
            PhotoIngestMessage(
                channel_id=123,
                message_id=1,
                author_id=42,
                content="hello",
                attachment_count=1,
            )
        )
    )

    assert result.handled is False
    assert result.status == "ignored_channel"


def test_photo_ingest_service_handles_attachment_messages_in_configured_channel() -> None:
    service = PhotoIngestService(
        settings=_settings(photo_ingest_channel_id=123),
        adapter=PhotoIngestAdapter(base_path=None),
        feature_flags=_feature_flags(),
    )

    result = asyncio.run(
        service.handle_message(
            PhotoIngestMessage(
                channel_id=123,
                message_id=1,
                author_id=42,
                content="see attached",
                attachment_count=2,
            )
        )
    )

    assert result.handled is True
    assert result.status == "placeholder_ready"


def test_photo_ingest_service_attaches_compressed_photo_to_service_request(tmp_path: Path) -> None:
    bluefolder_package = tmp_path / "bluefolder_api"
    bluefolder_package.mkdir()
    (bluefolder_package / "__init__.py").write_text("", encoding="utf-8")
    (bluefolder_package / "client.py").write_text(
        textwrap.dedent(
            """
            import base64

            LAST_UPLOAD = {}

            class _Attachments:
                def add_to_service_request(self, service_request_id, file_name, file_data_base64, description="", content_type="application/octet-stream"):
                    LAST_UPLOAD["service_request_id"] = service_request_id
                    LAST_UPLOAD["file_name"] = file_name
                    LAST_UPLOAD["description"] = description
                    LAST_UPLOAD["content_type"] = content_type
                    LAST_UPLOAD["size"] = len(base64.b64decode(file_data_base64))
                    return {"ok": True}

            class BlueFolderClient:
                def __init__(self, base_url: str | None = None):
                    self.base_url = base_url
                    self.attachments = _Attachments()
            """
        ),
        encoding="utf-8",
    )
    service = PhotoIngestService(
        settings=_settings(),
        adapter=PhotoIngestAdapter(
            bluefolder_api_path=str(tmp_path),
            bluefolder_api_key="key",
            bluefolder_account_name="acme",
        ),
        feature_flags=_feature_flags(),
    )

    result = asyncio.run(
        service.attach_model_serial_photo(
            12345,
            photo=PhotoAttachmentPayload(
                filename="photo.png",
                content_type="image/png",
                data=_image_bytes("PNG"),
            ),
            requested_by_user_id=99,
        )
    )

    sys_path = str(tmp_path)
    import sys
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    from bluefolder_api.client import LAST_UPLOAD  # type: ignore

    assert "Attached `photo.jpg` to `SR-12345`" in result.message
    assert LAST_UPLOAD["service_request_id"] == 12345
    assert LAST_UPLOAD["file_name"] == "photo.jpg"
    assert "Discord user 99" in LAST_UPLOAD["description"]
    assert LAST_UPLOAD["content_type"] == "image/jpeg"
    assert LAST_UPLOAD["size"] > 0


def test_photo_ingest_service_archives_photo_batch_via_email() -> None:
    sent_messages: list[object] = []

    class _DummySMTP:
        def __init__(self, host, port, timeout=30):
            assert host == "smtp.example.com"
            assert port == 587

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def starttls(self):
            return None

        def login(self, username, password):
            assert username == "user"
            assert password == "pass"

        def send_message(self, message):
            sent_messages.append(message)

    import smtplib

    original_smtp = smtplib.SMTP
    smtplib.SMTP = _DummySMTP  # type: ignore[assignment]
    try:
        service = PhotoIngestService(
            settings=_settings(),
            adapter=PhotoIngestAdapter(
                archive_smtp_host="smtp.example.com",
                archive_smtp_port=587,
                archive_smtp_username="user",
                archive_smtp_password="pass",
                archive_from_email="from@example.com",
                archive_to_email="to@example.com",
            ),
            feature_flags=_feature_flags(),
        )

        result = asyncio.run(
            service.archive_job_photos(
                12345,
                photos=[
                    PhotoAttachmentPayload(
                        filename="one.png",
                        content_type="image/png",
                        data=_image_bytes("PNG"),
                    ),
                    PhotoAttachmentPayload(
                        filename="two.png",
                        content_type="image/png",
                        data=_image_bytes("PNG"),
                    ),
                ],
                requested_by_user_id=77,
                sr_subject="Washer repair",
            )
        )
    finally:
        smtplib.SMTP = original_smtp  # type: ignore[assignment]

    assert result.message == "Emailed `2` compressed photo(s) for `SR-12345` to the archive mailbox."
    assert len(sent_messages) == 1
    message = sent_messages[0]
    assert message["Subject"] == "SR-12345 Washer repair"
    attachments = list(message.iter_attachments())
    assert len(attachments) == 2
    assert all(part.get_filename().endswith(".jpg") for part in attachments)


def test_photo_ingest_service_respects_disabled_mdlsn_feature() -> None:
    service = PhotoIngestService(
        settings=_settings(),
        adapter=PhotoIngestAdapter(),
        feature_flags=_feature_flags(mdlsn_upload=False),
    )

    result = asyncio.run(
        service.attach_model_serial_photo(
            12345,
            photo=PhotoAttachmentPayload(filename="one.png", content_type="image/png", data=_image_bytes("PNG")),
            requested_by_user_id=7,
        )
    )

    assert result.message == "Model/serial photo upload is currently disabled."


def test_photo_ingest_service_respects_disabled_archive_feature() -> None:
    service = PhotoIngestService(
        settings=_settings(),
        adapter=PhotoIngestAdapter(),
        feature_flags=_feature_flags(photo_archive_handoff=False),
    )

    result = asyncio.run(
        service.archive_job_photos(
            12345,
            photos=[PhotoAttachmentPayload(filename="one.png", content_type="image/png", data=_image_bytes("PNG"))],
            requested_by_user_id=7,
        )
    )

    assert result.message == "Photo archive handoff is currently disabled."


def test_photo_ingest_service_reports_matching_archived_photos() -> None:
    import imaplib

    class _DummyMailbox:
        def login(self, username, password):
            assert username == "mail-user"
            assert password == "mail-pass"

        def select(self, folder):
            assert folder == "INBOX"
            return "OK", [b""]

        def search(self, charset, *criteria):
            assert "SINCE" in criteria
            return "OK", [b"1 2"]

        def fetch(self, message_id, _query):
            if message_id == b"1":
                return "OK", [(b"1 (RFC822 {123})", _mk_email("Re: 12345 Washer repair", ["model_tag.jpg", "serial_tag.jpg"]))]
            return "OK", [(b"2 (RFC822 {123})", _mk_email("SR-99999 Other", ["before.jpg"]))]

        def close(self):
            return "OK", [b""]

        def logout(self):
            return "BYE", [b""]

    original_imap = imaplib.IMAP4_SSL
    imaplib.IMAP4_SSL = lambda host, port: _DummyMailbox()  # type: ignore[assignment]
    try:
        service = PhotoIngestService(
            settings=_settings(),
            adapter=PhotoIngestAdapter(
                mailbox_imap_host="mail.example.com",
                mailbox_imap_port=993,
                mailbox_imap_username="mail-user",
                mailbox_imap_password="mail-pass",
            ),
            feature_flags=_feature_flags(photo_mailbox_scan=True),
        )

        result = asyncio.run(service.get_photo_status(12345))
    finally:
        imaplib.IMAP4_SSL = original_imap  # type: ignore[assignment]

    assert "Mailbox status: `present`" in result.message
    assert "Found `1` matching email(s) with `2` photo attachment(s) for SR-12345." in result.message
    assert "Re: 12345 Washer repair" in result.message
    assert "Found required tags: `model`, `serial`" in result.message
    assert "Missing required tags: none" in result.message


def test_photo_ingest_service_reports_disabled_mailbox_scan() -> None:
    service = PhotoIngestService(
        settings=_settings(),
        adapter=PhotoIngestAdapter(),
        feature_flags=_feature_flags(photo_mailbox_scan=False),
    )

    result = asyncio.run(service.get_photo_status(12345))

    assert result.message == "Photo mailbox scan is currently disabled."


def test_photo_ingest_service_evaluates_missing_photo_reminder() -> None:
    class _Adapter(PhotoIngestAdapter):
        async def get_photo_compliance_summary(self, sr_id: int):
            from ops_hub.models.requests import PhotoComplianceSummary

            return PhotoComplianceSummary(
                sr_id=sr_id,
                mailbox_status="missing",
                message="No archived photo email was found for SR-12345.",
                matched_records=[],
                total_photos=0,
                found_tags=[],
                missing_tags=["model", "serial"],
            )

    class _BlueFolderStub:
        async def get_job_summary(self, reference: str) -> BlueFolderJobSummary:
            return BlueFolderJobSummary(
                reference=reference,
                available=True,
                integration_status="live_read",
                message="ok",
                service_request_id="12345",
                subject="Washer repair",
                service_request_status="Completed",
            )

        async def get_assignments_for_user_today(self, user_id: int) -> list[dict[str, str]]:
            if user_id == 13051:
                return [{"id": "12345"}]
            return []

    class _NotificationsStub:
        def __init__(self) -> None:
            self.messages: list[tuple[str, str]] = []

        async def send_notice(self, *, topic: str, message: str) -> None:
            self.messages.append((topic, message))

    service = PhotoIngestService(
        settings=_settings(photo_required_sr_statuses=["Completed"]),
        adapter=_Adapter(),
        feature_flags=_feature_flags(photo_mailbox_scan=True),
        bluefolder_service=_BlueFolderStub(),  # type: ignore[arg-type]
        technician_directory_service=type(
            "_DirectoryStub",
            (),
            {"reverse_mappings": lambda self: {13051: 42}},
        )(),
        notifications=_NotificationsStub(),  # type: ignore[arg-type]
    )

    result = asyncio.run(service.evaluate_photo_reminder(12345, send_notice=True))

    assert "Service request status: `Completed`" in result.message
    assert "Photo-required status match: `yes`" in result.message
    assert "Should notify: `yes`" in result.message
    assert "Reminder notice sent." in result.message


def test_photo_ingest_service_skips_reminder_when_status_not_required() -> None:
    class _Adapter(PhotoIngestAdapter):
        async def get_photo_compliance_summary(self, sr_id: int):
            from ops_hub.models.requests import PhotoComplianceSummary

            return PhotoComplianceSummary(
                sr_id=sr_id,
                mailbox_status="missing",
                message="No archived photo email was found for SR-12345.",
                matched_records=[],
                total_photos=0,
                found_tags=[],
                missing_tags=["model", "serial"],
            )

    class _BlueFolderStub:
        async def get_job_summary(self, reference: str) -> BlueFolderJobSummary:
            return BlueFolderJobSummary(
                reference=reference,
                available=True,
                integration_status="live_read",
                message="ok",
                service_request_id="12345",
                subject="Washer repair",
                service_request_status="In Progress",
            )

        async def get_assignments_for_user_today(self, user_id: int) -> list[dict[str, str]]:
            return [{"id": "12345"}]

    service = PhotoIngestService(
        settings=_settings(photo_required_sr_statuses=["Completed"]),
        adapter=_Adapter(),
        feature_flags=_feature_flags(photo_mailbox_scan=True),
        bluefolder_service=_BlueFolderStub(),  # type: ignore[arg-type]
        technician_directory_service=type(
            "_DirectoryStub",
            (),
            {"reverse_mappings": lambda self: {13051: 42}},
        )(),
    )

    result = asyncio.run(service.evaluate_photo_reminder(12345))

    assert "Photo-required status match: `no`" in result.message
    assert "Should notify: `no`" in result.message


def _mk_email(subject: str, attachment_names: list[str]) -> bytes:
    """Build a raw email with image attachments."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = "tech@example.com"
    message["To"] = "photos@example.com"
    message["Date"] = "Tue, 24 Mar 2026 10:00:00 -0400"
    message.set_content("photo handoff")
    for filename in attachment_names:
        message.add_attachment(
            _image_bytes("JPEG"),
            maintype="image",
            subtype="jpeg",
            filename=filename,
        )
    return message.as_bytes()


def _image_bytes(image_format: str) -> bytes:
    """Build a small in-memory image for upload/archive tests."""
    image = Image.new("RGB", (120, 80), color=(200, 30, 30))
    output = io.BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()
