# Security policy

Do not open a public issue containing an access token, capture, address, coordinates, serial
number, UUID, connection identifier, account identifier, IP address, VPN metadata, or complete
diagnostic payload.

Report security issues privately to the repository owner. Rotate any credential that may have
been disclosed.

## Safety boundary

The integration authorizes writes by discovered object classification, not by the presence of a
writable-looking field. Physical equipment is always read-only. All write methods validate the
target and allowed fields immediately before the network call.

## Test data

Only synthetic fixtures are accepted. Production HTTP/WebSocket captures must not be committed,
even after simple regex-based sanitization.
