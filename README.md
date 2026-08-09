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
- Safe light, binary Control, percentage Control, heater setpoint, and Theme activation operations.
- Controller-derived water-feature route groups. A route group is enabled only when the
  controller reports its shared Control group, body, flow procedure, pump, and valve endpoint.
  Route actions are sent as one high-level Control batch; physical pumps and valves are never
  addressed directly.
- Diagnostics with recursive credential and personal-information redaction.
- Reauthentication, reconnect handling, and explicit unavailable states.

Schedule mutation, Theme deactivation, and direct LAN control remain disabled until their exact
protocols and concurrency behavior are confirmed.

## Install locally

1. Run `make package` and locate `dist/poolside-<version>.zip`, or download the
   `poolside-home-assistant` artifact from a successful CI build.
2. Extract the ZIP into Home Assistant's `config/custom_components` folder. The resulting path
   must be `config/custom_components/poolside/manifest.json`.
3. Optionally verify the ZIP against the adjacent `.sha256` file.
4. Restart Home Assistant.
5. Open **Settings → Devices & services → Add integration → Poolside**.
6. Enter your Poolside email and password.

### Native homeowner dashboard

Use Home Assistant's native cards for all ordinary controls. Poolside publishes a native
**Light** entity for lighting, a native **Fan** entity for every verified variable-speed
blower, a native **Climate** entity for every heater with a confirmed setpoint, read-only
telemetry sensors, and a native Calendar. The bundled custom cards provide the dashboard-only
Pool/Spa view rail and the optional homeowner summary; ordinary controls remain native entities.

Copy [`docs/native-dashboard.yaml`](docs/native-dashboard.yaml) into a new manual dashboard,
then replace each example entity ID with the matching discovered entity from **Settings →
Devices & services → Poolside**. Omit a card when that entity is not discovered or is disabled.
The integration registers both bundled cards locally during startup, so no separate frontend
repository or HACS card installation is required. Existing `custom:poolside-dashboard` cards
will load again; the native template remains the recommended path for new dashboards.

Home Assistant intentionally does not let an integration silently rewrite a user's Lovelace
storage dashboard. The integration therefore does not overwrite an existing Overview view;
copying the supplied template is the safe one-time dashboard step.

### Optional body selector card

The integration serves its bundled Lovelace card locally at
`/poolside/poolside-body-selector.js` and registers it automatically. After a restart, reload
the browser with **Ctrl/Cmd+Shift+R** and add **Custom: Poolside Body Selector** from the card
picker.

For older Home Assistant builds that do not show automatically registered resources, add this
URL under **Settings → Dashboards → ⋮ → Resources → Add resource** as a JavaScript module:

```text
/poolside/poolside-body-selector.js
```

After adding or changing a resource, reload the browser with **Ctrl/Cmd+Shift+R**. The card is
then added from the dashboard editor as **Custom: Poolside Body Selector**.

If it does not appear in the picker, add a **Manual** card and paste this YAML:

```yaml
type: custom:poolside-body-selector
entity: select.poolside_active_body
name: Dashboard body
```

Configure the card with the Poolside body selector entity. It renders a discrete
multi-state slider. Selecting a body changes only the dashboard view; it cannot move
valves, switch pumps, or bypass Poolside. Selecting **Off** asks for confirmation and then
submits one safe batch that turns off the active high-level water-flow Controls in that
connected group. Lights, setpoints, schedules, and telemetry remain untouched.

The selector's `confirmed_water_flow` attribute is the controller-confirmed hydraulic state.
Use it for automations that need physical-state confirmation; do not treat the dashboard body
selection as a pump/valve command.

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
