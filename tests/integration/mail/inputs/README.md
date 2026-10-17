# mail inputs

Function under test: `notify_unresolved(service_name, tool_name, report, service_uuid=, source=, endpoint=)`
(`backend/app/codegen/verifier/utilities.py`), with the real `get_business_email` and
`send_failure_email`. These are the arguments `hit_endpoint` passes after the 5th failed attempt.

| File | Feeds | Format |
|---|---|---|
| `notify_call.json` | positional/keyword arguments | `{"service_name", "tool_name", "service_uuid", "report"}` (the failure report text) |
| `source.py` | `source=` | the tool file as last cached in Redis; becomes the attachment |
| `endpoint.json` | `endpoint=` | one MappedService endpoint entry (`method`, `path_template`, ...) |
| `businesses_table.json` | the Postgres `businesses` table (emulated behind an injected connection) | `[{"service_uuid", "business_name", "service_names", "email"}]` |
| `env.json` | environment variables | `MODE` (`null` = local outbox, `aws` = SES), `AMAZON_SUPPORT_EMAIL`, `ALERT_FROM_EMAIL` |
| `transport.json` | how the mail leaves | `{"transport": "outbox"}` or `{"transport": "ses", "ses_error": "<message the SES client raises>"}` |

Expected output (`../expected/<case>/`):
- `success`: `email.json` (status + From/To/Cc/subject/body/attachment names) and `attachment.py`.
- `failure`: `email.json` = `{"status": "failed", "outbox_files": 0, "ses_send_attempts": 1}`.
Date and Message-ID headers are not compared.
