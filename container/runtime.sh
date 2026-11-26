#!/usr/bin/env bash
# Prepare matching operator tools and plugin assets without starting GeoServer.
set -euo pipefail
cd "$(dirname "$0")/.."
engine=${CONTAINER_ENGINE:-podman}
image=docker.osgeo.org/geoserver:3.0.2-gdal
operator=${ENC_OPERATOR_IMAGE:-localhost/enc-operator:3.0.2}
archive=geoserver-3.0.2-s57-plugin.zip
offline=false
if [[ ${1:-} == --offline ]]; then offline=true; fi
# Send setup output to stderr and return only the resolved asset path on stdout.
exec 3>&1 1>&2
if "$offline"; then
  "$engine" image inspect "$image" "$operator" >/dev/null
else
  "$engine" image inspect "$image" >/dev/null 2>&1 || "$engine" pull "$image"
  "$engine" image inspect "$operator" >/dev/null 2>&1 || "$engine" build -f container/operator.Dockerfile -t "$operator" .
  [[ -s dist/$archive ]] || container/build-plugins.sh
fi
(cd dist && sha256sum -c "$archive.sha256")
stock_id=$("$engine" image inspect --format '{{.Id}}' "$image")
zip_hash=$(sha256sum "dist/$archive" | cut -d' ' -f1)
assets="$PWD/dist/runtime/${stock_id#sha256:}-$zip_hash"
if [[ ! -d $assets ]]; then
  mkdir -p "$(dirname "$assets")"
  stage=$(mktemp -d "$(dirname "$assets")/staging.XXXXXXXX")
  trap 'rm -rf -- "$stage"' EXIT
  chmod 755 "$stage"
  "$engine" run --rm --pull=never --network none --volume "$stage:/opt/enc/s57" --volume "$PWD/dist/$archive:/plugin.zip:ro" \
    --entrypoint sh "$operator" -ec '
      ogrinfo --format S57 >/dev/null && ogrinfo --format GPKG >/dev/null && ogrinfo --format SQLite >/dev/null
      python3 /opt/enc/scripts/inland_dictionary.py /usr/share/gdal /opt/enc/s57
      test -s /opt/enc/s57/s57objectclasses.csv
      unzip -p /plugin.zip "*.jar" > /opt/enc/s57/gs-s57.jar.tmp
      mv /opt/enc/s57/gs-s57.jar.tmp /opt/enc/s57/gs-s57.jar'
  if ! mv -T "$stage" "$assets"; then test -s "$assets/gs-s57.jar"; fi
fi
printf '%s\n' "$assets" >&3
