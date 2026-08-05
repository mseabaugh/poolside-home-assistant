# Poolside for Home Assistant

Poolside is an unofficial, safety-first custom integration for Poolside Tech's The Attendant.
It runs inside a local Home Assistant installation and currently communicates with the
Poolside cloud. No direct controller LAN protocol has been verified.

> [!WARNING]
> This project is not affiliated with or supported by Poolside Tech. Pool equipment can cause
> injury or property damage. This integration never writes directly to pumps, valves, heaters,
> chemical equipment, probes, relays, or controller internals.

## Current release scope

- UI configuration using a Poolside email and password exchanged through `User.login`.
- Dynamic discovery of sites, Controls, Combined Controls, Themes, schedules, and equipment.
- Cloud-push updates with periodic reconciliation.
- Read-only equipment telemetry and schedule calendar entities.
- Safe light, binary Control, percentage Control, and Theme activation operations.
- Diagnostics with recursive credential and personal-information redaction.
- Reauthentication, reconnect handling, and explicit unavailable states.

Schedule mutation, heating writes, Theme deactivation, and direct LAN control remain disabled
until their exact protocols and concurrency behavior are confirmed.

## Install locally

1. Run `make package` and locate `dist/poolside-<version>.zip`, or download the
   `poolside-home-assistant` artifact from a successful CI build.
2. Extract the ZIP into Home Assistant's `config/custom_components` folder. The resulting path
   must be `config/custom_components/poolside/manifest.json`.
3. Optionally verify the ZIP against the adjacent `.sha256` file.
4. Restart Home Assistant.
5. Open **Settings → Devices & services → Add integration → Poolside**.
6. Enter your Poolside email and password.

### Optional body selector card

The integration serves its bundled Lovelace card locally at
`/poolside/poolside-body-selector.js`. Open **Settings → Dashboards → ⋮ → Resources → Add
resource**, use this URL, and select **JavaScript module**:

```text
/poolside/poolside-body-selector.js
```

After adding or changing a resource, reload the browser with **Ctrl/Cmd+Shift+R**. The card is
then added from the dashboard editor as **Custom: Poolside Body Selector**.

If it does not appear in the picker, add a **Manual** card and paste this YAML:

```yaml
type: custom:poolside-body-selector
entity: select.poolside_active_body
name: Active body
```

Configure the card with the Poolside body selector entity. It renders a discrete
multi-state slider and asks for confirmation before changing from one active body
to another. The card is presentation-only; the integration remains responsible for
validating the authoritative state.

Poolside body relationships are grouped only when the service explicitly reports
them through `Spillover.ConnectedThings` or a cross-body `CombinedControl`. Bodies
without those signals remain independent and do not share an XOR selector.

The returned bearer token is stored in the Home Assistant config entry; the username and password
are never stored, included in diagnostics, or written to logs.

## Developer workflow

```bash
make bootstrap
make check
make e2e
make package
make test
make dev-up
```

`make dev-up` starts an isolated Home Assistant instance and a synthetic Poolside service. It
also starts Loki, Alloy, and Grafana. It never uses production credentials or production
Poolside endpoints. Home Assistant is available at `http://localhost:8123` and the provisioned
Grafana dashboard at `http://localhost:3300`.

See [Architecture](docs/ARCHITECTURE.md), [Testing](docs/TESTING.md),
[Operations](docs/OPERATIONS.md), [Security](SECURITY.md), and
[Contributing](CONTRIBUTING.md).

## Project status

This repository is alpha software. Read-only discovery and synthetic-service behavior are safe
to develop and test. Enable real write behavior only on equipment you own and supervise.
