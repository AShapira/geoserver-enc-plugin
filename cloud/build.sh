#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
case ${1:-} in 3.0.0|3.0.2) tag=$1 ;; *) echo 'usage: cloud/build.sh 3.0.0|3.0.2' >&2; exit 2 ;; esac
engine=${CONTAINER_ENGINE:-podman}
"$engine" build -f cloud/config.Dockerfile --build-arg CLOUD_TAG="$tag" -t "localhost/enc-cloud-config:$tag" .
for service in wms rest webui wfs gwc; do
  "$engine" build -f cloud/Dockerfile --build-arg CLOUD_TAG="$tag" --build-arg SERVICE="$service" \
    -t "localhost/enc-cloud-$service:$tag" .
done
