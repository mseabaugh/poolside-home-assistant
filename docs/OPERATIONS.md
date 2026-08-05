# Local operations

## Synthetic development stack

Run `make dev-up` to build and start Home Assistant, the synthetic Poolside service, Loki,
Grafana Alloy, and Grafana. No production token or Poolside endpoint is used.

- Home Assistant: `http://localhost:8123`
- Grafana: `http://localhost:3300` (override with `GRAFANA_PORT`)

The pre-provisioned **Poolside Home Assistant** dashboard shows RPC rate, outcome counts,
latency, safe logs, and correlation IDs. Alloy tails Home Assistant's file log from the isolated
named volume and sends it to Loki. The integration remains the single logging source.

Use `make dev-logs` for container startup problems. Use `make dev-down` to stop the stack and
delete only its named synthetic database and Grafana volumes.

## Real local Home Assistant

Copy `custom_components/poolside` to `<HA_CONFIG>/custom_components/poolside`, restart Home
Assistant, then add **Poolside** under **Settings → Devices & services**. The integration process
runs locally, while its currently verified transport reaches Poolside's cloud over HTTPS and
WebSocket.

Poolside authentication and connection failures are emitted at Home Assistant's warning level
with safe correlation metadata, so they appear in **Settings → System → Logs** without extra
configuration. For successful RPCs and protocol diagnostics, enable the integration's debug
logger in `configuration.yaml` and restart Home Assistant:

```yaml
logger:
  default: warning
  logs:
    custom_components.poolside: debug
```

Connection failures include an `error_type` such as `HTTP_400`, `HTTP_500`, `ClientConnectorError`,
`ClientConnectorDNSError`, or `TimeoutError`, plus the response `content_type` when available; this
identifies the failure class without logging the endpoint, response body, or credentials.

Do not set `POOLSIDE_TEST_MODE=1` in a real deployment. That flag exists solely so isolated tests
can substitute synthetic endpoints. Direct controller LAN transport is not implemented because
the handoff did not prove a LAN wire protocol.

## Failure handling

- HTTP or WebSocket authentication failures start Home Assistant reauthentication.
- An authenticated `ping` heartbeat runs every four minutes, before the five-minute
  reconciliation interval, so sliding Poolside sessions are kept active without storing the
  username or password. A rejected heartbeat stops the listener and starts reauthentication.
- Connectivity and protocol failures mark entities unavailable while periodic reconciliation and
  bounded reconnect behavior continue.
- Diagnostics recursively redact credentials, identity, location, and network metadata.
- Heating, physical-equipment, schedule, and Theme-off writes remain unavailable by design.
