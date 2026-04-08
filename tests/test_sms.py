from ops_hub.services.sms import DispatchSmsService, SmsAuditStore, SmsSendRecord, TwilioSmsAdapter


def test_sms_capabilities_normalize_phone_and_disable_unwired_twilio() -> None:
    service = DispatchSmsService(
        adapter=TwilioSmsAdapter(
            account_sid="sid",
            auth_token="token",
            from_number="+12065550100",
        ),
        store=SmsAuditStore(),
    )

    payload = service.capabilities_payload(
        sr_id=100,
        reference="SR-100",
        customer={"customerPhone": "(207) 555-0100"},
        work={"nextActions": ["Call for quote follow-up"]},
    )

    assert payload["enabled"] is False
    assert payload["toNumber"] == "+12075550100"
    assert payload["reason"] == "Twilio adapter wiring is not complete yet."


def test_sms_preview_uses_template_for_blank_custom_message_and_rejects_overlong_input() -> None:
    service = DispatchSmsService(store=SmsAuditStore())

    payload = service.preview_payload(
        sr_id=100,
        reference="SR-100",
        customer={"customerPhone": "2075550100"},
        work={},
        intent="dispatch_follow_up",
        custom_message="   ",
    )

    assert "SR-100" in payload["message"]

    try:
        service.preview_payload(
            sr_id=100,
            reference="SR-100",
            customer={"customerPhone": "2075550100"},
            work={},
            intent="dispatch_follow_up",
            custom_message="x" * 481,
        )
        assert False, "expected overlong custom message to fail"
    except ValueError as exc:
        assert "too long" in str(exc)


def test_sms_audit_store_caps_retained_records() -> None:
    store = SmsAuditStore(max_records=2)
    store.append(
        SmsSendRecord(
            sr_id=1,
            reference="SR-1",
            intent="dispatch_follow_up",
            provider="dry_run",
            status="dry_run",
            to_number="+12075550100",
            message="one",
        )
    )

    store.append(
        SmsSendRecord(
            sr_id=1,
            reference="SR-1",
            intent="dispatch_follow_up",
            provider="dry_run",
            status="dry_run",
            to_number="+12075550100",
            message="two",
        )
    )
    store.append(
        SmsSendRecord(
            sr_id=1,
            reference="SR-1",
            intent="dispatch_follow_up",
            provider="dry_run",
            status="dry_run",
            to_number="+12075550100",
            message="three",
        )
    )

    assert [item.message for item in store.records] == ["two", "three"]
