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

## Release and HACS deployment

Keep the release process consistent so HACS sees the same build that is on `main`:

1. Run the full gates: `make check`, `make e2e`, and `make package`.
2. Commit the validated changes to `main` with the version in
   `custom_components/poolside/manifest.json` and `const.py`.
3. Create an annotated tag with the exact version: `git tag -a vX.Y.Z -m "Release X.Y.Z"`.
4. Push both refs: `git push origin main` and `git push origin vX.Y.Z`.
5. Create a published, non-draft GitHub release from that tag with the title
   `Poolside vX.Y.Z` (the title must match the established naming convention).
6. Verify the release tag and `main` resolve to the same commit before telling users to
   refresh HACS.

Do not publish a release from a different branch, use a different version string in the
release title, or claim deployment before the remote commit, tag, and release are verified.
