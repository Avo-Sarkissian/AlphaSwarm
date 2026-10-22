#!/usr/bin/env bash
# Start, stop or reset the throwaway neo4j-test database (tmpfs, 127.0.0.1:7688).
#
# Tests never touch the dev database on 7687 (docs/DECISIONS.md#adr-tests-scoped-cleanup).
# Use this wrapper instead of raw Compose commands, which bite twice:
#   1. Compose interpolates the whole file, so the dev service's required
#      ${ALPHASWARM_NEO4J__PASSWORD:?...} aborts even `up neo4j-test` on a shell
#      without that variable. neo4j-test never uses it, so this script exports a
#      placeholder for its own process only. An exported real value passes
#      through untouched; nothing is written anywhere.
#   2. `docker compose --profile test down` without a service name also stops
#      and removes the dev container `alphaswarm-neo4j` (killing any running
#      simulation). Even with a service name, `down` deletes the project network
#      when no running container uses it, so a stopped dev container could no
#      longer start. Every command below names neo4j-test, and stopping uses
#      `rm`, which never touches networks.
#
# Usage: scripts/neo4j_test.sh up|down|reset|status
set -euo pipefail

cd "$(dirname "$0")/.."
export ALPHASWARM_NEO4J__PASSWORD="${ALPHASWARM_NEO4J__PASSWORD:-unused-by-neo4j-test}"

compose() { docker compose --profile test "$@"; }

case "${1:-}" in
  up)     compose up -d --wait neo4j-test ;;
  down)   compose rm --force --stop --volumes neo4j-test ;;
  reset)  compose rm --force --stop --volumes neo4j-test && compose up -d --wait neo4j-test ;;
  status) compose ps neo4j-test ;;
  *)      echo "usage: scripts/neo4j_test.sh up|down|reset|status" >&2; exit 2 ;;
esac
