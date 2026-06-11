#!/bin/bash
# Dump the AlphaSwarm Neo4j database to data/backups/.
#
# Why this exists: all pre-June-2026 cycle history was lost to an unscoped
# test-fixture delete. The fixture is fixed, but a dump is the only real
# insurance. Run before risky work, or weekly:
#   ./scripts/backup_neo4j.sh
#
# neo4j-admin dump requires the database to be stopped, so this briefly
# stops/starts the container (~15s downtime). Don't run mid-simulation.
set -euo pipefail
cd "$(dirname "$0")/.."

CONTAINER=alphaswarm-neo4j
BACKUP_DIR="data/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "Stopping $CONTAINER for a consistent dump..."
docker stop "$CONTAINER" >/dev/null

# Run neo4j-admin in a throwaway container sharing the data volume,
# dumping into the container's /backups (bind-mounted to $BACKUP_DIR).
docker run --rm \
  --volumes-from "$CONTAINER" \
  -v "$(pwd)/$BACKUP_DIR":/backups \
  neo4j:5.26-community \
  neo4j-admin database dump neo4j --to-path=/backups >/dev/null

mv "$BACKUP_DIR/neo4j.dump" "$BACKUP_DIR/neo4j-$STAMP.dump"

echo "Restarting $CONTAINER..."
docker start "$CONTAINER" >/dev/null

# Keep the 8 most recent dumps.
ls -t "$BACKUP_DIR"/neo4j-*.dump 2>/dev/null | tail -n +9 | xargs rm -f 2>/dev/null || true

echo "Backup written: $BACKUP_DIR/neo4j-$STAMP.dump ($(du -h "$BACKUP_DIR/neo4j-$STAMP.dump" | cut -f1))"
echo "Restore with: docker stop $CONTAINER && docker run --rm --volumes-from $CONTAINER -v \$(pwd)/$BACKUP_DIR:/backups neo4j:5.26-community neo4j-admin database load neo4j --from-path=/backups --overwrite-destination=true && docker start $CONTAINER"
