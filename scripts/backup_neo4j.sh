#!/bin/bash
# Dump the AlphaSwarm Neo4j database to data/backups/.
#
# Why this exists: all pre-June-2026 cycle history was lost to an unscoped
# test-fixture delete. The fixture is fixed, but a dump is the only real
# insurance. Run before risky work, or weekly:
#   ./scripts/backup_neo4j.sh
#
# Which container: this repo has had two over its life — `alphaswarm-neo4j`
# (created by docker-compose.yml) and `neo4j` (created by the older `docker
# run` recipe the README used to carry). An earlier version of this script
# hardcoded `alphaswarm-neo4j` and would silently dump whichever container
# had that name even when the live database was the other one, producing
# backups of an empty or stale volume. It now resolves the container, refuses
# to guess, and verifies the dump is non-empty before reporting success.
# Override with: ALPHASWARM_NEO4J_CONTAINER=<name> ./scripts/backup_neo4j.sh
#
# neo4j-admin dump requires the database to be stopped, so this briefly
# stops/starts the container. Don't run mid-simulation.
set -euo pipefail
cd "$(dirname "$0")/.."

BACKUP_DIR="data/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"

# --- Resolve the container -------------------------------------------------
if [[ -n "${ALPHASWARM_NEO4J_CONTAINER:-}" ]]; then
  CONTAINER="$ALPHASWARM_NEO4J_CONTAINER"
  if ! docker container inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "error: no container named '$CONTAINER'." >&2
    exit 1
  fi
else
  FOUND=()
  for candidate in alphaswarm-neo4j neo4j; do
    if docker container inspect "$candidate" >/dev/null 2>&1; then
      FOUND+=("$candidate")
    fi
  done
  if [[ ${#FOUND[@]} -eq 0 ]]; then
    echo "error: found no Neo4j container (looked for: alphaswarm-neo4j, neo4j)." >&2
    echo "       Start one with 'docker compose up -d', or set" >&2
    echo "       ALPHASWARM_NEO4J_CONTAINER=<name>." >&2
    exit 1
  fi
  if [[ ${#FOUND[@]} -gt 1 ]]; then
    # Refusing to guess is the whole point: picking wrong is how the old
    # script produced worthless backups without anyone noticing.
    echo "error: more than one Neo4j container exists: ${FOUND[*]}" >&2
    echo "       Pick one explicitly:" >&2
    echo "         ALPHASWARM_NEO4J_CONTAINER=<name> $0" >&2
    echo "       'docker ps -a --filter name=neo4j' shows which is running." >&2
    exit 1
  fi
  CONTAINER="${FOUND[0]}"
fi

# --- Resolve the image -----------------------------------------------------
# neo4j-admin must match the store format, so run it from the SAME image the
# container itself uses rather than a pinned tag. A hardcoded 5.26 tag cannot
# read a store written by a 2026.x server, which is the second way the old
# script failed. Use the image ID, not the tag, since tags move.
IMAGE="$(docker container inspect --format '{{.Image}}' "$CONTAINER")"

WAS_RUNNING="$(docker container inspect --format '{{.State.Running}}' "$CONTAINER")"

mkdir -p "$BACKUP_DIR"

if [[ "$WAS_RUNNING" == "true" ]]; then
  echo "Stopping $CONTAINER for a consistent dump..."
  docker stop "$CONTAINER" >/dev/null
else
  echo "$CONTAINER is already stopped; dumping in place."
fi

restart_if_needed() {
  if [[ "$WAS_RUNNING" == "true" ]]; then
    echo "Restarting $CONTAINER..."
    docker start "$CONTAINER" >/dev/null
  fi
}
# Restart even if the dump fails, so a bad run never leaves the DB down.
trap restart_if_needed EXIT

# Run neo4j-admin in a throwaway container sharing the data volume,
# dumping into the container's /backups (bind-mounted to $BACKUP_DIR).
docker run --rm \
  --volumes-from "$CONTAINER" \
  -v "$(pwd)/$BACKUP_DIR":/backups \
  "$IMAGE" \
  neo4j-admin database dump neo4j --to-path=/backups >/dev/null

if [[ ! -s "$BACKUP_DIR/neo4j.dump" ]]; then
  echo "error: neo4j-admin produced no dump (or an empty one)." >&2
  exit 1
fi

mv "$BACKUP_DIR/neo4j.dump" "$BACKUP_DIR/neo4j-$STAMP.dump"

# Keep the 8 most recent dumps.
ls -t "$BACKUP_DIR"/neo4j-*.dump 2>/dev/null | tail -n +9 | xargs rm -f 2>/dev/null || true

echo "Backup written: $BACKUP_DIR/neo4j-$STAMP.dump ($(du -h "$BACKUP_DIR/neo4j-$STAMP.dump" | cut -f1))"
echo "Container: $CONTAINER   Image: $IMAGE"
echo "Restore with: docker stop $CONTAINER && docker run --rm --volumes-from $CONTAINER -v \$(pwd)/$BACKUP_DIR:/backups $IMAGE neo4j-admin database load neo4j --from-path=/backups --overwrite-destination=true && docker start $CONTAINER"
