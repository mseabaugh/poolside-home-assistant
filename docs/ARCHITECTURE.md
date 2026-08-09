# Architecture

```text
Home Assistant UI and automations
            |
Home Assistant entity adapters
            |
Poolside coordinator and state registry
            |
Safety policy ---- schedule mutation gate
            |
Typed Poolside client
            |
Transport interface
      |                 |
Cloud transport    Future local transport
(implemented)      (unimplemented until verified)
```

The integration is installed and executed locally. Its currently proven transport is cloud
JSON-RPC over HTTPS and WebSocket. A direct LAN transport belongs behind the same interface and
must satisfy the same safety policy, but will not be implemented from guessed wire formats.

## Dependency direction

Protocol parsing, models, safety, redaction, and schedule logic do not import Home Assistant.
The coordinator injects a client. Entity adapters depend on coordinator snapshots and never call
the transport directly. This keeps safety enforceable and permits deterministic tests.

## Write boundary

Writable targets are discovered Controls, Combined Controls, and Themes. Equipment UUIDs are
never writable. Allowed fields are type-specific. Restricted or disabled Controls are rejected
before any network operation.

## Controller-derived water routing

Pool/Spa selection in the dashboard is a presentation context, not a hydraulic command. The
only group-level shutdown action collects the currently active discovered water-flow Controls
for one explicitly connected body group and sends one authorized `Site.setDesiredState2` batch.
It excludes lights, saved setpoints, schedules, Themes, raw pumps, valves, actuators, relays,
and telemetry.

The optional water-feature route UI appears only when the controller graph proves all of these
relationships by identifiers: a shared Control group, a body of water, a control-based flow
procedure, exactly one pump path, and at least one valve/actuator endpoint. The route selector
is display-only; the paired master switch writes the selected route (or Blend) as one high-level
Control batch. A missing or ambiguous graph edge removes the route group rather than guessing.

Schedule documents are readable. Mutation remains disabled until Poolside exposes a verified
atomic revision, precondition, or equivalent conflict mechanism. A process-local lock cannot
prevent another app from writing between a read and a write.

## Observability

Code uses Home Assistant's logger and records method, duration, outcome, retry state, and a
locally generated short correlation ID. It never records request bodies, credentials, or remote
identifiers. The local stack uses Grafana Alloy to collect Home Assistant logs into Loki and a
provisioned Grafana dashboard without a second application-side log transport.
