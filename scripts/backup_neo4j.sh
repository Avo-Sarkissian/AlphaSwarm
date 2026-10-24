#!/bin/bash
# Dump the AlphaSwarm Neo4j database to data/backups/ (or $ALPHASWARM_BACKUP_DIR).
#
# Why this exists: all pre-June-2026 cycle history was lost to an unscoped
# test-fixture delete. The fixture is fixed, but a dump is the only real
# insurance. Run before risky work, or weekly:
#   ./scripts/backup_neo4j.sh
#
# Safety (docs/RUNBOOK.md section 3):
#   - It refuses to run while a simulation is running: the web server's
#     /api/health reports is_simulation_running, or a CLI run/inject/report
#     holds the AlphaSwarm instance lock. Stopping Neo4j mid-run fails the
#     in-flight writes.
#   - neo4j-admin dump needs the database stopped, so it stops the container
#     with a 60 s grace period and always restarts it.
#   - It prints a restore sequence that works: neo4j-admin database load only
#     reads a file named neo4j.dump, so the sequence copies the backup to that
#     name in a fresh directory first.
#
# Which container: this repo has had two over its life, `alphaswarm-neo4j`
# (created by docker-compose.yml) and `neo4j` (created by the older `docker
# run` recipe the README used to carry). An earlier version of this script
# hardcoded `alphaswarm-neo4j` and would silently dump whichever container
# had that name even when the live database was the other one. It now
# resolves the container, refuses to guess, and verifies the dump is
# non-empty before reporting success.
#
# Overrides: ALPHASWARM_NEO4J_CONTAINER=<name>, ALPHASWARM_BACKUP_DIR=<dir>,
# ALPHASWARM_HEALTH_URL=<url> (default http://127.0.0.1:8000/api/health),
# ALPHASWARM_INSTANCE_LOCK=<file> (default ~/.alphaswarm/instance.lock).
set -euo pipefail
cd "$(dirname "$0")/.."

BACKUP_DIR="${ALPHASWARM_BACKUP_DIR:-data/backups}"
HEALTH_URL="${ALPHASWARM_HEALTH_URL:-http://127.0.0.1:8000/api/health}"
LOCK_FILE="${ALPHASWARM_INSTANCE_LOCK:-$HOME/.alphaswarm/instance.lock}"
STAMP="$(date +%Y%m%d-%H%M%S)"
EX_TEMPFAIL=75

# --- Refuse while a simulation runs ----------------------------------------
HEALTH_ANSWERED=0
if health="$(curl -fsS --max-time 3 "$HEALTH_URL" 2>/dev/null)"; then
  HEALTH_ANSWERED=1
  if grep -Eq '"is_simulation_running"[[:space:]]*:[[:space:]]*true' <<<"$health"; then
    echo "error: a simulation is running ($HEALTH_URL reports is_simulation_running)." >&2
    echo "       Stopping Neo4j now would fail its writes; run the backup after it finishes." >&2
    exit "$EX_TEMPFAIL"
  fi
fi

lock_holder() {
  # Prints the command holding the AlphaSwarm instance lock, or nothing.
  # Needs only the standard library, so any python3 will do.
  [[ -e "$LOCK_FILE" ]] || return 0
  local py=()
  if command -v python3 >/dev/null 2>&1; then
    py=(python3)
  elif command -v uv >/dev/null 2>&1; then
    py=(uv run --no-project python)
  else
    echo "warning: neither python3 nor uv found; cannot check the AlphaSwarm instance lock." >&2
    return 0
  fi
  "${py[@]}" - "$LOCK_FILE" <<'PY'
import fcntl, json, os, sys
fd = os.open(sys.argv[1], os.O_RDONLY)
try:
    fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
except BlockingIOError:
    try:
        holder = json.loads(os.pread(fd, 4096, 0) or b"{}")
    except ValueError:
        holder = {}
    print(holder.get("command", "unknown") if isinstance(holder, dict) else "unknown")
PY
}

HOLDER="$(lock_holder)"
case "$HOLDER" in
  "") ;;  # nothing holds the lock
  web)
    # The web server holds the lock, so only its health check can say it is idle;
    # a server too busy to answer may be mid-run, so no answer means refuse.
    if [[ "$HEALTH_ANSWERED" != 1 ]]; then
      echo "error: \`alphaswarm web\` holds $LOCK_FILE but $HEALTH_URL did not answer," >&2
      echo "       so a running simulation cannot be ruled out; retry when the server responds." >&2
      exit "$EX_TEMPFAIL"
    fi ;;
  *)
    echo "error: \`alphaswarm $HOLDER\` is running (it holds $LOCK_FILE)." >&2
    echo "       Stopping Neo4j now would fail its writes; run the backup after it finishes." >&2
    exit "$EX_TEMPFAIL" ;;
esac

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
# container uses (its image ID; tags move).
IMAGE="$(docker container inspect --format '{{.Image}}' "$CONTAINER")"
WAS_RUNNING="$(docker container inspect --format '{{.State.Running}}' "$CONTAINER")"

mkdir -p "$BACKUP_DIR"
BACKUP_DIR_ABS="$(cd "$BACKUP_DIR" && pwd)"
rm -f "$BACKUP_DIR_ABS/neo4j.dump"  # a leftover from a failed run would block the dump

if [[ "$WAS_RUNNING" == "true" ]]; then
  echo "Stopping $CONTAINER for a consistent dump (60 s grace period)..."
  docker stop -t 60 "$CONTAINER" >/dev/null
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

docker run --rm \
  --volumes-from "$CONTAINER" \
  -v "$BACKUP_DIR_ABS":/backups \
  "$IMAGE" \
  neo4j-admin database dump neo4j --to-path=/backups >/dev/null

if [[ ! -s "$BACKUP_DIR_ABS/neo4j.dump" ]]; then
  echo "error: neo4j-admin produced no dump (or an empty one)." >&2
  exit 1
fi

DUMP="$BACKUP_DIR_ABS/neo4j-$STAMP.dump"
mv "$BACKUP_DIR_ABS/neo4j.dump" "$DUMP"

# Keep the 8 most recent dumps.
ls -t "$BACKUP_DIR_ABS"/neo4j-*.dump 2>/dev/null | tail -n +9 | xargs rm -f 2>/dev/null || true

echo "Backup written: $DUMP ($(du -h "$DUMP" | cut -f1))"
echo "Container: $CONTAINER   Image: $IMAGE"
cat <<RESTORE

Restore this backup (stops Neo4j; never while a simulation runs).
neo4j-admin database load only reads a file named neo4j.dump, so copy it first:
  RESTORE_DIR="\$(mktemp -d)"
  cp "$DUMP" "\$RESTORE_DIR/neo4j.dump"
  docker stop -t 60 $CONTAINER
  docker run --rm --volumes-from $CONTAINER -v "\$RESTORE_DIR":/backups $IMAGE neo4j-admin database load neo4j --from-path=/backups --overwrite-destination=true
  docker start $CONTAINER
RESTORE
