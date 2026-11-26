#!/usr/bin/env bash
# Run an operator command with the same mount paths and network namespace as the server.
set -euo pipefail
engine=${CONTAINER_ENGINE:-podman}
name=${ENC_CONTAINER:-geoserver-enc}
image=$("$engine" inspect --format '{{index .Config.Labels "org.enc.operator"}}' "$name")
[[ -n $image && $image != '<no value>' ]] || { echo 'Recreate the ENC server with container/demo.sh first' >&2; exit 1; }
exec "$engine" run -i --rm --pull=never --network "container:$name" --volumes-from "$name" \
  -e GEOSERVER_USER -e GEOSERVER_PASSWORD -e GEOSERVER_URL -e ENC_REPORT -e ENC_INDEX -e ENC_SAFETY --entrypoint "$1" "$image" "${@:2}"
