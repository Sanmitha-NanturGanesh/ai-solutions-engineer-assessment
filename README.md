# FDE assessment — MCP and LLM gateways

I used Python for all four tasks so the same validation, async HTTP and test tooling could be reused across the project. Each task can run independently.

The assessment text says five tasks, but the material I received contains four detailed implementations. I added a short zero-trust troubleshooting note under `docs/` because it is called out in the role focus areas.

## What is here

```text
task1_mcp_server/       MCP stdio server + strict tool input validation
task2_mcp_gateway/      JSON-RPC proxy with tool-level authorization
task3_llm_guardrail/    streaming SSE proxy with incremental PII redaction
task4_model_router/     SQLite token limiter + primary/secondary routing
tests/                  focused tests for validation, auth, streaming and concurrency
docs/                   zero-trust troubleshooting notes
```

## Requirement check

| Assessment requirement | Where it is handled |
| --- | --- |
| MCP server with two tools | `task1_mcp_server/server.py` |
| Strict customer/refund validation | `task1_mcp_server/schemas.py` |
| JSON-RPC invalid-params errors | Task 1 converts Pydantic failures to `-32602` |
| stdio transport / stderr logging | Task 1 server startup and logging config |
| Bearer role + `admin_*` filtering | `task2_mcp_gateway/app.py` |
| `-32001` unauthorized tool call | Task 2 gateway before downstream forwarding |
| Streaming email / SSN / card redaction | `task3_llm_guardrail/redactor.py` |
| Partial-value handling across chunks | Task 3 incremental carry buffer |
| 50,000 tokens/minute per tenant | `task4_model_router/rate_limiter.py` |
| SQLite persistence | Task 4 rate-limit database |
| 3000 ms timeout + 429 fallback | `task4_model_router/app.py` |
| Sanitized gateway errors | Task 4 error response helper |
| Zero-trust troubleshooting | `docs/zero_trust_troubleshooting.md` |

## Setup

Python 3.11+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e '.[dev]'
pytest -q
```

## 1. Customer MCP server

Run:

```bash
python -m task1_mcp_server.server
```

Tools:

- `get_customer_record(customer_id)`
- `trigger_refund(customer_id, amount, reason)`

A customer ID must match `CUST-XXXXX`. Refund amount must be positive and the reason must contain at least 10 non-whitespace characters. Extra fields are rejected.

I used the low-level MCP server API here because the assessment explicitly scores JSON-RPC error behavior. Pydantic validation errors are converted to `INVALID_PARAMS (-32602)`. The validation error sent back contains field/type/message only; it does not echo the original input.

The server uses stdio, so stdout is treated as protocol-only. Logging is configured to stderr.

Example tool arguments:

```json
{"customer_id":"CUST-A1001"}
```

```json
{"customer_id":"CUST-A1001","amount":25.50,"reason":"Duplicate monthly charge"}
```

## 2. MCP security gateway

Start the mock downstream server:

```bash
uvicorn task2_mcp_gateway.mock_downstream:app --port 9001
```

Start the gateway:

```bash
uvicorn task2_mcp_gateway.app:app --port 8002
```

Viewer request that should be blocked:

```bash
curl -s http://127.0.0.1:8002/rpc \
  -H 'Authorization: Bearer viewer' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"admin_reset_key","arguments":{}}}'
```

The gateway returns JSON-RPC error `-32001` and does not contact the downstream service. `tools/list` is forwarded unchanged, as requested.

For the exercise, the bearer token itself is `admin` or `viewer` (also accepts `role:admin` / `role:viewer`). In a deployed service I would replace that small parser with verified JWT claims or token introspection; the authorization check would stay in the same place.

## 3. Streaming PII guardrail

Start the mock provider:

```bash
uvicorn task3_llm_guardrail.mock_provider:app --port 9002
```

Start the gateway:

```bash
uvicorn task3_llm_guardrail.app:app --port 8003
```

Try it:

```bash
curl -N http://127.0.0.1:8003/v1/generate \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"demo"}'
```

The redactor handles:

- email addresses
- SSNs in `123-45-6789` form
- 13–19 digit card candidates that pass Luhn validation

The important part is chunk boundaries. A provider can split `jane@example.com` between several SSE events, so checking each chunk independently can leak data. The redactor keeps only the trailing text that could still become a PII match and immediately emits the stable prefix. It never builds the full completion in memory.

I also preserve the provider's delta shape when possible instead of converting every SSE event into a different schema.

## 4. Token limiter and model fallback

Start both mock providers:

```bash
uvicorn task4_model_router.mock_primary:app --port 9003
uvicorn task4_model_router.mock_secondary:app --port 9004
```

Then start the router:

```bash
uvicorn task4_model_router.app:app --port 8004
```

Request:

```bash
curl -s http://127.0.0.1:8004/v1/completions \
  -H 'X-Tenant-API-Key: tenant-123' \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Explain MCP gateways","max_tokens":200}'
```

To exercise fallback with the included mock primary, add `"mock_mode":"429"` or `"mock_mode":"timeout"` to the JSON body.

The limiter reserves estimated prompt tokens plus `max_tokens` against a 50,000 token / 60 second budget per tenant. SQLite is in WAL mode and admission is done inside `BEGIN IMMEDIATE`, which keeps the check-and-insert atomic across concurrent requests.

Primary routing behavior:

```text
primary 2xx          -> return primary response
primary 429          -> call secondary
primary timeout      -> call secondary
other primary error  -> sanitized gateway error
```

The upstream timeout defaults to 3000 ms. Client-facing errors use a small gateway error schema and never include exception reprs, stack traces or raw provider response bodies.

### Token accounting note

The request is charged before the provider call. That is intentional: it prevents a tenant from starting more work than its budget permits. In a production gateway I would keep the reservation model but reconcile it against the provider's actual usage after the response.

## Tests I focused on

The tests cover the failure paths I would expect a reviewer to probe:

- malformed customer IDs, refund values and unexpected fields
- viewer blocked from `admin_*` and proof that downstream was not called
- admin forwarding and transparent `tools/list`
- email/SSN/card redaction, including values split across chunks
- no false card redaction for a failing-Luhn number
- per-tenant sliding-window expiry
- concurrent rate-limit admission without oversubscription

Run all tests with:

```bash
pytest -q
```

## Tradeoffs / what I would change for production

I kept the scope close to the assessment instead of building a full platform around it.

- **Auth:** verify JWT signatures, issuer/audience and scopes instead of using demo bearer values.
- **Rate limiting:** SQLite is appropriate for this single-host exercise and satisfies the requirement. For a multi-node gateway I would use an atomic shared quota service (for example Redis + Lua) or a dedicated rate-limit service.
- **PII:** regex + Luhn is useful for deterministic patterns. For broader sensitive-data detection I would add a policy engine/DLP service, but I would still keep deterministic fast-path rules for obvious PII.
- **Fallback:** I only fail over on 429 and timeout because those are the conditions in the prompt. I would not automatically retry every 5xx without defining idempotency and retry policy first.
- **Observability:** add correlation IDs, latency/fallback metrics and authorization audit events; avoid logging prompts, bearer tokens or unredacted model output.

## Zero-trust note

`docs/zero_trust_troubleshooting.md` is the checklist I would use when a client can authenticate but cannot reach an MCP or model service through a zero-trust deployment.
