# Confirmed protocol surface

The supplied evidence confirms cloud JSON-RPC endpoints and the following operations:

- Reads: `User.getConfig`, `Site.getStates`, `Site.getDesiredState`, `ping`.
- `ping` is also used as the authenticated session heartbeat; it does not return a replacement
  token, so an expired or rejected token correctly enters Home Assistant reauthentication.
- Writes: `Site.setDesiredState2`, `Site.setTheme` with `Status=ON`.
- Pushes: `Connection.activate`, `Site.setStates`, `Site.setDesiredState`,
  `Device.setConfig`, and `Site.updateAlerts`.

`Site.setConfig` full-document traffic was observed, but its remote concurrency behavior was not
confirmed. It is therefore not exposed as a production write.

Unknown push methods are ignored after a body-free debug log. Request bodies, remote IDs, and
full trace IDs are never logged. RPC completion logs include only a short, locally generated
correlation prefix, method, outcome, and duration.

## Body relationship evidence

The network capture includes explicit body relationships in the `User.getConfig` site document:

- `BodiesOfWater[*].Spillover.ConnectedThings[*].UUID` identifies connected bodies.
- `Controls[*].BodyOfWater` assigns a control to a body.
- `CombinedControls[*].Controls[*].ControlUUID` can be resolved back to controls and therefore
  identifies a cross-body combined control.

The integration uses only those explicit links when forming an XOR group. Bodies without a
spillover connection or cross-body combined control remain independent. The capture did not
confirm a dedicated Pool/Spa mode JSON-RPC method, so body switching must not invent a write
operation from telemetry alone.
