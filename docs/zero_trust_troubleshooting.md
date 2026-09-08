# Zero-trust troubleshooting notes

The assessment overview mentions zero-trust deployment troubleshooting, although the copy I received only includes four detailed coding tasks. This is the checklist I would use during an incident.

## Start with the failing hop

I would trace one request through:

```text
client -> gateway -> MCP/LLM service -> model/data dependency
```

At each hop I want a request/correlation ID, DNS result, TLS peer identity, status code and latency. That usually separates network, identity and application failures quickly.

## Checks

1. **Workload identity** — issuer, audience, expiry, clock skew, service account/workload identity and the role/scopes mapped from it.
2. **TLS / mTLS** — trust bundle, SAN/SNI, certificate expiry, protocol version, and whether a sidecar or ingress is terminating TLS at a different hop than expected.
3. **Authorization policy** — gateway RBAC plus service-mesh or workload policy. A request can be authenticated correctly and still be denied by method/path/service-account policy.
4. **Network policy** — namespace selectors, security groups/firewalls, egress policy and private endpoint rules.
5. **DNS** — resolve the service from inside the same pod/container/namespace. Check split-horizon/private-zone records rather than testing only from a laptop.
6. **Proxy settings** — `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, CONNECT behavior and HTTP/2 support where streaming requires it.
7. **MCP transport/version** — confirm the client and server negotiated a compatible MCP protocol and that the expected transport is actually being used.
8. **Streaming** — check reverse-proxy buffering and idle/read timeouts. A stream that works directly but stalls through ingress is often an intermediary issue.

## What I would log

Useful fields: request ID, tenant, authenticated principal, authorization decision, selected upstream, fallback reason, upstream status and timing.

I would not log bearer tokens, raw prompts, unredacted completions, secrets or raw stack traces.

For authorization, I prefer fail-closed behavior. For model routing, fallback should happen only for failures explicitly considered retryable.
