# Contributing

Use Python 3.14.2 or newer and make changes on a branch. Run `make check` and `make test` before
opening a pull request.

Every behavior change needs:

1. Unit tests for positive, boundary, and reasonable negative paths.
2. Integration tests with injected HTTP/WebSocket and Home Assistant resources.
3. An end-to-end scenario when user-visible behavior changes.
4. Documentation updates for new capabilities or limitations.

Never weaken the safety policy or coverage threshold to make a build pass. Never add real
Poolside identifiers or captures as fixtures.
