#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
engine=${CONTAINER_ENGINE:-podman}
name=${ENC_CONTAINER:-geoserver-enc}
export ENC_CONTAINER="$name"
image=docker.osgeo.org/geoserver:3.0.2-gdal
operator=${ENC_OPERATOR_IMAGE:-localhost/enc-operator:3.0.2}
archive=geoserver-3.0.2-s57-plugin.zip
offline=false
empty=false
recreate=false
for arg in "$@"; do
  case "$arg" in --offline) offline=true ;; --empty) empty=true ;; --recreate) recreate=true ;; *) echo "Unknown option: $arg" >&2; exit 2 ;; esac
done
runtime_args=()
if "$offline"; then runtime_args+=(--offline); fi
assets=$(container/runtime.sh "${runtime_args[@]}")
zip_hash=$(sha256sum "dist/$archive" | cut -d' ' -f1)
operator_id=$("$engine" image inspect --format '{{.Id}}' "$operator")
data_volume=$name-data
cache_volume=$name-cache
catalogue_volume=$name-catalogue
if "$engine" container inspect "$name" >/dev/null 2>&1; then
  owner=$("$engine" inspect --format '{{index .Config.Labels "org.enc.project"}}' "$name")
  [[ $owner == geoserver-enc-plugin ]] || { echo "Existing $name is not owned by this project" >&2; exit 1; }
  volume_at() {
    "$engine" inspect --format "{{range .Mounts}}{{if eq .Destination \"$1\"}}{{.Name}}{{end}}{{end}}" "$name"
  }
  data_volume=$(volume_at /opt/geoserver_data)
  cache_volume=$(volume_at /opt/enc-cache)
  previous=$(volume_at /opt/enc-data)
  catalogue_volume=${previous:-$catalogue_volume}
  [[ -n $data_volume && -n $cache_volume ]] || { echo 'Expected named data and cache volumes' >&2; exit 1; }
  if "$recreate"; then
    "$engine" stop --time 15 "$name"
    "$engine" rm "$name"
  elif [[ $("$engine" inspect --format '{{index .Config.Labels "org.enc.archive"}}' "$name") != "$zip_hash" ]]; then
    echo 'Run with --recreate to switch this server to the selected plugin archive.' >&2
    exit 1
  fi
fi
for volume in "$data_volume" "$cache_volume" "$catalogue_volume"; do
  "$engine" volume inspect "$volume" >/dev/null 2>&1 || "$engine" volume create "$volume"
done
if "$engine" container inspect "$name" >/dev/null 2>&1; then
  "$engine" start "$name"
else
  network=(-p "127.0.0.1:${ENC_PORT:-18080}:8080")
  if [[ ${ENC_NETWORK:-} == none ]]; then network=(--network none); fi
  admin=()
  if [[ -n ${GEOSERVER_PASSWORD:-} ]]; then
    export GEOSERVER_ADMIN_USER=${GEOSERVER_USER:-admin} GEOSERVER_ADMIN_PASSWORD=$GEOSERVER_PASSWORD
    admin=(-e GEOSERVER_ADMIN_USER -e GEOSERVER_ADMIN_PASSWORD)
  fi
  "$engine" run -d --name "$name" --label org.enc.project=geoserver-enc-plugin \
    --label "org.enc.operator=$operator_id" --label "org.enc.archive=$zip_hash" --restart unless-stopped \
    --memory "${ENC_MEMORY:-6g}" "${network[@]}" "${admin[@]}" \
    -e SKIP_DEMO_DATA=true -e ROOT_WEBAPP_REDIRECT=true -e INSTALL_EXTENSIONS=false -e COMMUNITY_EXTENSIONS=s57 \
    -e EXTRA_JAVA_OPTS="-Xms256m -Xmx3g" \
    -v "$PWD/dist/$archive:/opt/additional_libs/$archive:ro" \
    -v "$assets:/opt/enc/s57:ro" -v "$PWD/scripts/ogr_inland.py:/opt/enc/scripts/ogr_inland.py:ro" \
    -v "$data_volume:/opt/geoserver_data" -v "$cache_volume:/opt/enc-cache" -v "$catalogue_volume:/opt/enc-data:ro" "$image"
fi
ready=false
for ((i=0;i<180;i++)); do
  if "$engine" exec "$name" curl -fsS 'http://127.0.0.1:8080/geoserver/ows?service=WMS&request=GetCapabilities' >/dev/null 2>&1; then ready=true; break; fi
  sleep 1
done
"$ready" || { "$engine" logs --tail 50 "$name"; exit 1; }
"$engine" exec "$name" sh -ec 'test -s /usr/local/tomcat/webapps/geoserver/WEB-INF/lib/gs-s57-*.jar; /opt/enc/scripts/ogr_inland.py --version; ogrinfo --format S57 >/dev/null; ogrinfo --format GPKG >/dev/null; ogrinfo --format SQLite >/dev/null; test -w /opt/enc-cache'
[[ $(container/operator.sh /usr/bin/ogr2ogr --version) == $("$engine" exec "$name" /usr/bin/ogr2ogr --version) ]] || { echo 'Operator and server GDAL versions differ' >&2; exit 1; }
if ! "$empty"; then
  download_network=()
  if "$offline"; then download_network=(--network none); fi
  "$engine" run --rm --pull=never "${download_network[@]}" -e "ENC_OFFLINE=$offline" -v "$catalogue_volume:/opt/enc-data" --entrypoint sh "$operator" -ec '
    if [ ! -f /opt/enc-data/catalogue.sqlite ]; then
      mkdir -p /opt/enc-data/downloads
      cd /opt/enc-data/downloads
      for file in ENCProdCat.xml All_ENCs.zip; do
        if [ ! -s "$file" ]; then
          [ "$ENC_OFFLINE" = false ] || { echo "Missing /opt/enc-data/downloads/$file" >&2; exit 1; }
          curl -fL --retry 3 "https://charts.noaa.gov/ENCs/$file" -o "$file.partial"
          mv "$file.partial" "$file"
        fi
      done
      python3 /opt/enc/scripts/catalogue.py --catalogue ENCProdCat.xml --archive All_ENCs.zip --out /opt/enc-data
    fi'
  container/operator.sh python3 /opt/enc/scripts/deployment.py existing-noaa --if-missing
  container/operator.sh python3 /opt/enc/scripts/warm_catalogue.py --catalogue /opt/enc-data/catalogue.sqlite --cache /opt/enc-cache
  container/operator.sh java -Xmx2g -cp '/opt/enc/s57/gs-s57.jar:/usr/local/tomcat/webapps/geoserver/WEB-INF/lib/*' org.enc.geoserver.EdgeCache /opt/enc-data/catalogue.sqlite /opt/enc-cache /usr/bin/ogr2ogr "${ENC_EDGE_WORKERS:-4}"
  GEOSERVER_PASSWORD=${GEOSERVER_PASSWORD:-geoserver} container/operator.sh python3 /opt/enc/scripts/tune_cache.py --url http://127.0.0.1:8080/geoserver --apply --seed --report /opt/enc-cache/tuning-report.json
fi
if [[ ${ENC_NETWORK:-} == none ]]; then
  printf 'Viewer available inside %s at http://localhost:8080/geoserver/enc/viewer/index.html\n' "$name"
else
  printf 'Viewer: http://127.0.0.1:%s/geoserver/enc/viewer/index.html\n' "${ENC_PORT:-18080}"
fi
