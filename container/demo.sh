#!/usr/bin/env bash
# Dedicated named volumes; no host bind mounts, privileged mode, or engine socket.
set -euo pipefail
cd "$(dirname "$0")/.."
engine=${CONTAINER_ENGINE:-podman}
image=localhost/geoserver-enc:catalogue
name=geoserver-enc
format=()
if [[ "$engine" == *podman ]]; then format=(--format docker); fi
"$engine" build "${format[@]}" -f container/Dockerfile -t "$image" .
for volume in geoserver-enc-catalogue geoserver-enc-cache geoserver-enc-data; do
  "$engine" volume inspect "$volume" >/dev/null 2>&1 || "$engine" volume create "$volume"
done
"$engine" run --rm --volume geoserver-enc-catalogue:/opt/enc-data --entrypoint /bin/bash "$image" -c '
  set -euo pipefail
  if [[ ! -f /opt/enc-data/catalogue.sqlite ]]; then
    mkdir -p /opt/enc-data/downloads
    curl -fL --retry 3 https://charts.noaa.gov/ENCs/ENCProdCat.xml -o /opt/enc-data/downloads/ENCProdCat.xml
    curl -fL --retry 3 https://charts.noaa.gov/ENCs/All_ENCs.zip -o /opt/enc-data/downloads/All_ENCs.zip
    python3 /opt/enc/scripts/catalogue.py --catalogue /opt/enc-data/downloads/ENCProdCat.xml --archive /opt/enc-data/downloads/All_ENCs.zip --out /opt/enc-data
  fi'
if "$engine" container inspect "$name" >/dev/null 2>&1; then
  owner=$("$engine" inspect --format '{{index .Config.Labels "org.enc.project"}}' "$name")
  [[ "$owner" == geoserver-enc-plugin ]] || { echo "Existing $name is not owned by this project" >&2; exit 1; }
  if [[ "${1:-}" == --recreate ]]; then
    "$engine" stop --time 15 "$name"
    "$engine" rm "$name" # Named volumes are retained; no --volumes flag.
  fi
fi
if "$engine" container inspect "$name" >/dev/null 2>&1; then
  "$engine" start "$name"
else
  "$engine" run -d --name "$name" --label org.enc.project=geoserver-enc-plugin --restart unless-stopped \
    --memory "${ENC_MEMORY:-6g}" \
    -p "127.0.0.1:${ENC_PORT:-18080}:8080" \
    --volume geoserver-enc-data:/opt/geoserver_data \
    --volume geoserver-enc-catalogue:/opt/enc-data:ro \
    --volume geoserver-enc-cache:/opt/enc-cache "$image"
fi
ready=false
for ((i=0;i<120;i++)); do
  if "$engine" exec "$name" curl -fsS 'http://127.0.0.1:8080/geoserver/ows?service=WMS&request=GetCapabilities&version=1.3.0' >/dev/null 2>&1; then ready=true;break;fi
  sleep 1
done
[[ "$ready" == true ]] || { "$engine" logs --tail 50 "$name"; exit 1; }
for palette in day dusk night; do
  "$engine" exec -e "GEOSERVER_PASSWORD=${GEOSERVER_PASSWORD:-geoserver}" "$name" \
    python3 /opt/enc/scripts/publish.py --catalogue /opt/enc-data/catalogue.sqlite --url http://127.0.0.1:8080/geoserver \
    --workspace noaa --data-dir /opt/geoserver_data --cache /opt/enc-cache --ogr2ogr /usr/bin/ogr2ogr \
    --styles "/opt/enc/generated-$palette" --palette "$palette" --update
 done
"$engine" exec "$name" python3 /opt/enc/scripts/warm_catalogue.py --catalogue /opt/enc-data/catalogue.sqlite --cache /opt/enc-cache
"$engine" exec "$name" java -Xmx2g -cp '/usr/local/tomcat/webapps/geoserver/WEB-INF/lib/*' \
  org.enc.geoserver.EdgeCache /opt/enc-data/catalogue.sqlite /opt/enc-cache /usr/bin/ogr2ogr "${ENC_EDGE_WORKERS:-4}"
"$engine" exec -e "GEOSERVER_PASSWORD=${GEOSERVER_PASSWORD:-geoserver}" "$name" python3 /opt/enc/scripts/tune_cache.py \
  --url http://127.0.0.1:8080/geoserver --apply --seed --report /opt/enc-cache/tuning-report.json
printf '\nOpen http://127.0.0.1:%s/enc.html\n' "${ENC_PORT:-18080}"
