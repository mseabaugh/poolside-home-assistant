# Testing strategy

The build has three independent test layers:

- **Unit:** pure protocol, parsing, state, safety, redaction, light codec, and schedule behavior.
- **Integration:** Home Assistant config flow, lifecycle, coordinator, entity, diagnostics, and
  reauthentication behavior with injected external resources.
- **End-to-end:** a real Home Assistant container, synthetic Poolside HTTP/WebSocket service,
  isolated Home Assistant database, and Playwright browser.

Coverage.py enforces 100% statements and branches over integration-owned Python across the test
matrix. CI combines parallel coverage data and fails if either metric is below 100%. Each layer
also has a scenario manifest; adding a supported write requires a matching E2E scenario.

Common failures covered include invalid/expired tokens, timeouts, malformed JSON-RPC, HTTP and
WebSocket disconnects, reconnect backoff, out-of-order push messages, unknown pushes, restricted
Controls, equipment-write attempts, partial discovery data, duplicate sites, stale schedule
documents, failed confirmations, and recursive secret redaction.

Run `make check` for formatting, lint, strict types, Compose validation, and the Python coverage
gate. Run `make e2e` for the disposable browser stack. `make build` requires both and then builds
the versioned installable ZIP and local images. `make package` runs both gates before writing the
ZIP and SHA-256 checksum under `dist/`. The browser scenario performs fresh HA onboarding, adds the integration in the
UI, toggles a Lovelace entity, verifies the synthetic service received the mutation, and deletes
the isolated test volume on exit.
