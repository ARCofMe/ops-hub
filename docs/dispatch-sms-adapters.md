# Dispatch SMS Adapters

This is the recommended shape for adding SMS notifications to RouteDesk and Ops Hub without coupling the workflow to one vendor.

## Goals

- let dispatch-triggered SMS send from Ops Hub, not directly from the browser
- keep Twilio easy to adopt first
- keep the provider boundary small enough that Telnyx, MessageBird, Plivo, or another SMS vendor can replace it later
- separate message intent from provider delivery details
- preserve auditability, retry behavior, and opt-out safety

## Recommended architecture

1. `RouteDesk` emits intent, not provider calls.
   Example actions:
   - notify customer that the tech is en route
   - request missing model/serial info
   - confirm quote approval is still needed
   - confirm parts are ready and dispatch is trying to schedule

2. `ops-hub` owns message composition and delivery orchestration.
   That keeps:
   - API tokens off the frontend
   - audit trails and delivery logs in one place
   - rate limiting and retry policy centralized
   - future non-SMS transports easier to add

3. `ops-hub` talks to an adapter interface such as:

```python
class SmsAdapter(Protocol):
    async def send_message(
        self,
        *,
        to_number: str,
        body: str,
        metadata: dict[str, str] | None = None,
    ) -> SmsSendResult: ...
```

4. Provider-specific adapters implement the same contract.
   First candidates:
   - `TwilioSmsAdapter`
   - `TelnyxSmsAdapter`
   - `MockSmsAdapter` for local/dev/test

5. Delivery results get normalized into one shared result model, for example:

```python
@dataclass(slots=True)
class SmsSendResult:
    success: bool
    provider: str
    provider_message_id: str | None = None
    status: str | None = None
    error_code: str | None = None
    error_message: str | None = None
```

## Ops Hub service shape

Recommended layers:

- `SmsTemplateService`
  Builds message text from SR context, customer context, and operator intent.

- `SmsPolicyService`
  Decides whether a message is allowed.
  Example checks:
  - valid mobile number
  - customer opted in
  - no recent duplicate send for the same intent
  - correct SR status/stage for the message type

- `SmsNotificationService`
  Executes sends through the active adapter and persists delivery history.

- `SmsAuditStore`
  Persists:
  - SR id
  - recipient number
  - message intent
  - rendered body
  - actor
  - provider
  - provider message id
  - delivery status
  - error details

## Recommended provider-agnostic intents

These should be stable internal actions no matter which SMS vendor is active:

- `dispatch.en_route`
- `dispatch.need_model_serial`
- `dispatch.quote_follow_up`
- `dispatch.parts_ready_follow_up`
- `dispatch.schedule_follow_up`
- `dispatch.customer_response_needed`

The UI should choose an intent; Ops Hub should render the final message.

## RouteDesk UI seam

Best first placement is inside:

- `Service Request`
  Customer phone and context are already present there.

- `Triage`
  Good for missing-info and quote/approval follow-up.

- `Attention`
  Good for quick dispatch-triggered follow-up when the queue already says a customer touch is needed.

Recommended flow:

1. operator clicks `Send SMS`
2. RouteDesk requests a server-rendered preview
3. operator reviews/editable body if allowed
4. RouteDesk submits a send request
5. Ops Hub records and returns delivery result

## API seam

Suggested endpoints:

- `GET /dispatch/sr/<sr_id>/sms_capabilities`
- `POST /dispatch/sr/<sr_id>/sms/preview`
- `POST /dispatch/sr/<sr_id>/sms/send`
- `GET /dispatch/sr/<sr_id>/sms/history`

Preview/send bodies should be provider-agnostic:

```json
{
  "intent": "dispatch.need_model_serial",
  "toNumber": "+12075551212",
  "overrides": {
    "body": "Optional operator-edited message"
  }
}
```

## Configuration

Keep config provider-specific but service selection generic:

- `OPS_HUB_SMS_PROVIDER=twilio`
- `OPS_HUB_SMS_FROM_NUMBER=...`
- `OPS_HUB_SMS_AUDIT_FILE=...`

Provider-specific examples:

- `OPS_HUB_TWILIO_ACCOUNT_SID`
- `OPS_HUB_TWILIO_AUTH_TOKEN`
- `OPS_HUB_TWILIO_MESSAGING_SERVICE_SID`

The service container should instantiate the adapter from `OPS_HUB_SMS_PROVIDER`.

## Delivery webhooks

If the chosen provider supports status callbacks, Ops Hub should expose a webhook endpoint that updates delivery records without changing the frontend contract.

Recommended normalized final states:

- `queued`
- `sent`
- `delivered`
- `failed`
- `undeliverable`

## Guardrails

- do not let the browser call the SMS vendor directly
- normalize all phone numbers to E.164 before send
- add per-intent dedupe windows
- keep customer opt-out state separate from vendor account state
- log message content carefully if privacy rules require redaction
- treat retries for send failures differently from retries for webhook sync failures

## First implementation cut

1. build `MockSmsAdapter`
2. add SMS preview/send/history endpoints in Ops Hub
3. add one RouteDesk entry point in `Service Request`
4. support one provider adapter, likely Twilio first
5. add delivery audit and webhook updates

That gets a usable system in place without hardcoding RouteDesk to one SMS provider.
