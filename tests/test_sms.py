from ops_hub.services.sms import DispatchSmsService, SmsAuditStore, TwilioSmsAdapter


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
