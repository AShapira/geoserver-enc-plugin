#!/usr/bin/env bash
# Run inside Kartoza's container, with optional Pillow installed and
# GEOSERVER_PASSWORD set to the REST administrator password.
set -euo pipefail
data_dir=${GEOSERVER_DATA_DIR:-/opt/geoserver/data_dir}
command=(python3 /opt/enc/scripts/publish.py
  --url http://127.0.0.1:8080/geoserver
  --data-dir "$data_dir" --cache "$data_dir/enc-cache"
  --ogr2ogr /usr/bin/ogr2ogr --styles "$data_dir/enc-generated")
# Kartoza uses this same USER environment variable for its service account.
# Default docker exec runs as root; avoid root-owned workspace/style directories.
if [[ $(id -u) == 0 ]]; then
  exec gosu "${USER:-geoserveruser}" "${command[@]}" "$@"
fi
exec "${command[@]}" "$@"
