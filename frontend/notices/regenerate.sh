#!/bin/sh
# Rebuild the notice store (notices/notices.json) and the provenance register (notices/sources.lock.json), then check them.
# Needs: Python >= 3.9, Node >= 22.18, network access (about 0.5 GB of npm tarballs, cached in notices/.evidence/cache) and the backend Docker image
# (`docker compose build`; it is only read). Environment overrides: OUT (evidence folder), LOCK (provenance register), CACHE (download cache).
set -eu
cd "$(dirname "$0")/.."
OUT=${OUT:-notices/.evidence}
LOCK=${LOCK:-notices/sources.lock.json}
python3 notices/tools/evidence.py --out "$OUT" --lock "$LOCK" ${CACHE:+--cache "$CACHE"}
node scripts/collect-notices.mjs --evidence "$OUT" | head -4
node scripts/check-sbom.mjs
node scripts/verify-notices.mjs --lock "$LOCK"
