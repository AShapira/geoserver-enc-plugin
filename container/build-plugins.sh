#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
engine=${CONTAINER_ENGINE:-podman}
builder=localhost/enc-builder:3.13.3
mkdir -p dist "${ENC_MAVEN_CACHE:=$PWD/.runtime/plugin-maven}"
opts=()
args=()
if [[ ${1:-} == --offline ]]; then
  opts+=(--network none --pull=never)
  args+=(--offline)
elif [[ $# == 0 ]]; then
  "$engine" build -f container/builder.Dockerfile -t "$builder" .
else
  echo 'usage: container/build-plugins.sh [--offline]' >&2
  exit 2
fi
"$engine" run --rm "${opts[@]}" -v "$PWD:/work:ro" -v "$PWD/dist:/out" \
  -v "$ENC_MAVEN_CACHE:/maven" -e S57_TEST_FILE -e S57_CATALOGUE -e OGR2OGR=ogr2ogr \
  --entrypoint python3 "$builder" scripts/package.py --repository /maven --output /out "${args[@]}"
