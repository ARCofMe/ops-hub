"""SMS service boundary for dispatch-facing customer messaging."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ops_hub.services.file_store_utils import atomic_write_text


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class SmsSendRecord:
    """Persisted SMS attempt for one service request."""

    sr_id: int
    reference: str
    intent: str
    provider: str
    status: str
    to_number: str
    message: str
    actor_user_id: int | None = None
    sent_at: str = field(default_factory=_utc_now)
    external_id: str | None = None
    error: str | None = None


@dataclass(slots=True)
class SmsAuditStore:
    """File-backed audit store for dispatch SMS attempts."""

    file_path: Path | None = None
    records: list[SmsSendRecord] = field(default_factory=list)

    def load(self) -> list[SmsSendRecord]:
        """Load persisted SMS records if configured."""
        if self.file_path is None or not self.file_path.exists():
            return list(self.records)
        try:
            raw = json.loads(self.file_path.read_text(encoding="utf-8"))
        except Exception:
            self.records = []
            return []
        if not isinstance(raw, list):
            raise RuntimeError(f"SMS audit file must contain a JSON array: {self.file_path}")
        self.records = [SmsSendRecord(**item) for item in raw if isinstance(item, dict)]
        return list(self.records)

    def append(self, record: SmsSendRecord) -> Path | None:
        """Append and persist one SMS audit record."""
        self.records.append(record)
        if self.file_path is None:
            return None
        atomic_write_text(
            self.file_path,
            json.dumps([asdict(item) for item in self.records], indent=2),
        )
        return self.file_path

    def recent_for_sr(self, sr_id: int, *, limit: int = 10) -> list[SmsSendRecord]:
        """Return the newest audit records for one service request."""
        if limit <= 0:
            return []
        matches = [record for record in self.records if int(record.sr_id) == int(sr_id)]
        return list(reversed(matches[-limit:]))


@dataclass(slots=True)
class SmsSendResult:
    """Normalized outbound SMS result."""

    provider: str
    status: str
    to_number: str
    message: str
    external_id: str | None = None
    error: str | None = None


class SmsAdapter:
    """Provider-agnostic SMS adapter contract."""

    provider_name = "unknown"

    def delivery_status(self) -> tuple[bool, str | None]:
        """Return whether this adapter can actually send messages right now."""
        return True, None

    async def send_message(self, *, to_number: str, message: str) -> SmsSendResult:
        raise NotImplementedError


class DryRunSmsAdapter(SmsAdapter):
    """Audit-only adapter used until a real SMS provider is enabled."""

    provider_name = "dry_run"

    async def send_message(self, *, to_number: str, message: str) -> SmsSendResult:
        return SmsSendResult(
            provider=self.provider_name,
            status="dry_run",
            to_number=to_number,
            message=message,
        )


class TwilioSmsAdapter(SmsAdapter):
    """Twilio-shaped adapter placeholder for future provider wiring."""

    provider_name = "twilio"

    def __init__(
        self,
        *,
        account_sid: str | None = None,
        auth_token: str | None = None,
        from_number: str | None = None,
        messaging_service_sid: str | None = None,
    ) -> None:
        self.account_sid = (account_sid or "").strip()
        self.auth_token = (auth_token or "").strip()
        self.from_number = (from_number or "").strip()
        self.messaging_service_sid = (messaging_service_sid or "").strip()

    def delivery_status(self) -> tuple[bool, str | None]:
        if not (self.account_sid and self.auth_token and (self.from_number or self.messaging_service_sid)):
            return False, "Twilio credentials are not configured yet."
        return False, "Twilio adapter wiring is not complete yet."

    async def send_message(self, *, to_number: str, message: str) -> SmsSendResult:
        enabled, reason = self.delivery_status()
        if not enabled:
            return SmsSendResult(
                provider=self.provider_name,
                status="unconfigured" if reason == "Twilio credentials are not configured yet." else "pending_provider_wiring",
                to_number=to_number,
                message=message,
                error=reason,
            )
        return SmsSendResult(
            provider=self.provider_name,
            status="queued",
            to_number=to_number,
            message=message,
        )


@dataclass(slots=True)
class DispatchSmsService:
    """Dispatch-facing SMS orchestration with provider-agnostic templates."""

    adapter: SmsAdapter = field(default_factory=DryRunSmsAdapter)
    store: SmsAuditStore = field(default_factory=SmsAuditStore)
    from_label: str = "ARCoM Ops"

    def __post_init__(self) -> None:
        self.store.load()

    def capabilities_payload(
        self,
        *,
        sr_id: int,
        reference: str,
        customer: dict[str, object] | None,
        work: dict[str, object] | None,
    ) -> dict[str, object]:
        """Return current SMS availability and supported intents for one SR."""
        to_number = self._resolve_phone_number(customer)
        adapter_enabled, adapter_reason = self.adapter.delivery_status()
        intents = self._intents(reference=reference, work=work)
        return {
            "srId": sr_id,
            "reference": reference,
            "provider": self.adapter.provider_name,
            "enabled": bool(to_number) and adapter_enabled,
            "toNumber": to_number,
            "fromLabel": self.from_label,
            "reason": self._capability_reason(to_number=to_number, adapter_reason=adapter_reason),
            "intents": intents,
        }

    def preview_payload(
        self,
        *,
        sr_id: int,
        reference: str,
        customer: dict[str, object] | None,
        work: dict[str, object] | None,
        intent: str,
        custom_message: str | None = None,
    ) -> dict[str, object]:
        """Build one preview payload without sending anything."""
        to_number = self._resolve_phone_number(customer)
        if not to_number:
            raise ValueError("No customer phone number is available for this SR.")
        message = self._render_message(
            reference=reference,
            customer=customer,
            work=work,
            intent=intent,
            custom_message=custom_message,
        )
        return {
            "srId": sr_id,
            "reference": reference,
            "intent": intent,
            "provider": self.adapter.provider_name,
            "toNumber": to_number,
            "message": message,
            "segments": self._segment_count(message),
        }

    async def send_payload(
        self,
        *,
        sr_id: int,
        reference: str,
        customer: dict[str, object] | None,
        work: dict[str, object] | None,
        intent: str,
        actor_user_id: int | None,
        custom_message: str | None = None,
    ) -> dict[str, object]:
        """Send one SMS through the configured adapter and record the attempt."""
        preview = self.preview_payload(
            sr_id=sr_id,
            reference=reference,
            customer=customer,
            work=work,
            intent=intent,
            custom_message=custom_message,
        )
        result = await self.adapter.send_message(
            to_number=str(preview["toNumber"]),
            message=str(preview["message"]),
        )
        record = SmsSendRecord(
            sr_id=sr_id,
            reference=reference,
            intent=intent,
            provider=result.provider,
            status=result.status,
            to_number=result.to_number,
            message=result.message,
            actor_user_id=actor_user_id,
            external_id=result.external_id,
            error=result.error,
        )
        self.store.append(record)
        return {
            "success": result.status in {"sent", "queued", "dry_run"},
            "provider": result.provider,
            "status": result.status,
            "toNumber": result.to_number,
            "message": result.message,
            "error": result.error,
            "externalId": result.external_id,
        }

    def history_payload(self, *, sr_id: int) -> dict[str, object]:
        """Return recent SMS attempts for one service request."""
        records = self.store.recent_for_sr(sr_id)
        return {
            "srId": sr_id,
            "items": [
                {
                    "sentAt": record.sent_at,
                    "intent": record.intent,
                    "provider": record.provider,
                    "status": record.status,
                    "toNumber": record.to_number,
                    "message": record.message,
                    "actorUserId": record.actor_user_id,
                    "externalId": record.external_id,
                    "error": record.error,
                }
                for record in records
            ],
        }

    @staticmethod
    def _normalize_phone_number(value: str | None) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) == 11 and digits.startswith("1"):
            return f"+{digits}"
        if len(digits) == 10:
            return f"+1{digits}"
        return raw

    def _capability_reason(self, *, to_number: str | None, adapter_reason: str | None) -> str | None:
        if not to_number:
            return "No customer phone number is available for this SR."
        return adapter_reason

    def _resolve_phone_number(self, customer: dict[str, object] | None) -> str | None:
        if not isinstance(customer, dict):
            return None
        direct = self._normalize_phone_number(customer.get("customerPhone"))
        if direct:
            return direct
        contacts = customer.get("contacts")
        if not isinstance(contacts, list):
            return None
        for contact in contacts:
            if not isinstance(contact, dict):
                continue
            phone = self._normalize_phone_number(contact.get("phone"))
            if phone:
                return phone
        return None

    def _intents(self, *, reference: str, work: dict[str, object] | None) -> list[dict[str, str]]:
        next_actions = {str(action).strip().lower() for action in (work or {}).get("nextActions", []) if str(action).strip()}
        intents = [
            ("dispatch_follow_up", "General follow-up"),
            ("dispatch_need_model_serial", "Need model/serial"),
            ("dispatch_quote_follow_up", "Quote follow-up"),
            ("dispatch_parts_ready_follow_up", "Parts ready follow-up"),
            ("dispatch_schedule_follow_up", "Schedule follow-up"),
        ]
        payload: list[dict[str, str]] = []
        for key, label in intents:
            recommended = "false"
            if key == "dispatch_need_model_serial" and any("model" in action or "serial" in action for action in next_actions):
                recommended = "true"
            elif key == "dispatch_quote_follow_up" and any("quote" in action for action in next_actions):
                recommended = "true"
            elif key == "dispatch_parts_ready_follow_up" and any("part" in action for action in next_actions):
                recommended = "true"
            elif key == "dispatch_schedule_follow_up" and any("schedule" in action for action in next_actions):
                recommended = "true"
            elif key == "dispatch_follow_up" and not payload:
                recommended = "true"
            payload.append({"key": key, "label": label, "recommended": recommended, "reference": reference})
        return payload

    def _render_message(
        self,
        *,
        reference: str,
        customer: dict[str, object] | None,
        work: dict[str, object] | None,
        intent: str,
        custom_message: str | None = None,
    ) -> str:
        custom = str(custom_message or "").strip()
        if custom:
            return self._bounded_message(custom)

        customer_name = str((customer or {}).get("customerName") or "").strip() or "there"
        subject = str((customer or {}).get("subject") or "").strip() or "your service request"
        status = str((work or {}).get("serviceRequestStatus") or (customer or {}).get("status") or "").strip()

        templates = {
            "dispatch_follow_up": (
                f"{self.from_label}: Hi {customer_name}, we're following up on {reference} ({subject}). "
                "Reply here or call the office if you need help."
            ),
            "dispatch_need_model_serial": (
                f"{self.from_label}: Hi {customer_name}, we need the model and serial for {reference} "
                f"({subject}) before we can move it forward."
            ),
            "dispatch_quote_follow_up": (
                f"{self.from_label}: Hi {customer_name}, {reference} is waiting on quote follow-up. "
                "Reply if you want us to review the next step with you."
            ),
            "dispatch_parts_ready_follow_up": (
                f"{self.from_label}: Hi {customer_name}, parts activity on {reference} is ready for follow-up. "
                "Reply if you want to schedule or confirm the next visit."
            ),
            "dispatch_schedule_follow_up": (
                f"{self.from_label}: Hi {customer_name}, we're ready to schedule {reference}. "
                "Reply with your availability and we can line it up."
            ),
        }
        message = templates.get(intent)
        if not message:
            raise ValueError(f"Unsupported SMS intent: {intent}")
        if status:
            message = f"{message} Current status: {status}."
        return self._bounded_message(" ".join(message.split()))

    @staticmethod
    def _segment_count(message: str) -> int:
        return max(1, (len(message) + 159) // 160)

    @staticmethod
    def _bounded_message(message: str) -> str:
        normalized = " ".join(str(message or "").split())
        if not normalized:
            raise ValueError("SMS message cannot be blank.")
        if len(normalized) > 480:
            raise ValueError("SMS message is too long. Keep it under 480 characters.")
        return normalized
