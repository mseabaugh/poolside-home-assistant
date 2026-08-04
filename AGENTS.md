# Repository Engineering Rules

- Preserve the physical-equipment safety boundary. Only discovered Poolside Controls,
  Combined Controls, and confirmed Theme operations are writable.
- Never infer writability from desired-state or telemetry fields.
- Never log or commit credentials, personal information, addresses, exact locations,
  serial numbers, connection identifiers, account identifiers, or production captures.
- Production code must never select a fake transport. Test endpoint overrides require the
  explicit `POOLSIDE_TEST_MODE=1` process environment flag.
- Preserve unknown protocol fields during full-document round trips.
- Add meaningful positive, boundary, failure, reconnect, stale-data, and security tests for
  every behavior change.
- Unit, integration, and end-to-end suites run on every build. Integration-owned Python must
  retain 100% statement and branch coverage without broad exclusions.
- Integration tests inject and mock HTTP, WebSocket, Home Assistant, and database resources.
- End-to-end tests use an isolated Home Assistant instance, synthetic Poolside service, and
  dedicated test database. They may mock only systems external to the whole application.
- Use Home Assistant logging APIs. Logs must be safe for forwarding to Promtail/Loki and
  correlation in Grafana without an additional application-side log sink.
- Every build must produce a working local Docker development stack. Terraform is not part of
  this repository because a Home Assistant integration is installed into a user-owned Home
  Assistant runtime rather than deployed as an AWS service.
- Track every material change in Git and keep each commit buildable.
