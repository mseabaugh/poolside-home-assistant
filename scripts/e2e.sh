#!/usr/bin/env bash
set -euo pipefail

cleanup() {
  docker compose --profile e2e --profile observability down --volumes
}
trap cleanup EXIT

cleanup
docker compose --profile e2e build fake-poolside e2e
docker compose --profile e2e up --detach --wait fake-poolside home-assistant
docker compose --profile e2e run --rm e2e
