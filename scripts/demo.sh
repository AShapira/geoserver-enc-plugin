#!/usr/bin/env bash
# Run after serve.sh is listening. Restores only this project's own workspace with --update.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$ENC_ROOT"
GEOSERVER_DATA_DIR="$ENC_ROOT/.runtime/geoserver/data_dir"
: "${GEOSERVER_PASSWORD:?Set GEOSERVER_PASSWORD (fresh loopback demo default: geoserver)}"
cell=$(python scripts/fetch_noaa.py "${ENC_CELL:-US5NY1BH}")
python scripts/publish.py "$cell" --url "http://127.0.0.1:${ENC_PORT:-18080}/geoserver" --data-dir "$GEOSERVER_DATA_DIR" \
  --cache .runtime/cache --ogr2ogr "$JAVA_HOME/bin/ogr2ogr" "$@"
python scripts/smoke_test.py
