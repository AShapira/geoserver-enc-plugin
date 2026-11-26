#!/usr/bin/env bash
# Export an installable kit, images and an optional offline Maven cache.
set -euo pipefail
cd "$(dirname "$0")/.."
dest=${1:?usage: airgap/export.sh OUTPUT_DIRECTORY [--with-builder]}
[[ $dest = /* ]] || dest="$PWD/$dest"
[[ $# == 1 || ( $# == 2 && $2 == --with-builder ) ]] || exit 2
mkdir -p "$dest"
engine=${CONTAINER_ENGINE:-podman}
stock=docker.osgeo.org/geoserver:3.0.2-gdal
operator=localhost/enc-operator:3.0.2
"$engine" image inspect "$stock" >/dev/null 2>&1 || "$engine" pull "$stock"
"$engine" build -f container/operator.Dockerfile -t "$operator" .
if [[ $# == 2 || ! -f dist/geoserver-3.0.2-s57-plugin.zip || ! -f dist/geoserver-2.28.0-s57-plugin.zip ]]; then
  container/build-plugins.sh
fi
python3 scripts/package_airgap.py --output "$dest/enc-kit.zip"
files=(enc-kit.zip stock.tar operator.tar)
"$engine" save -o "$dest/stock.tar" "$stock"
"$engine" save -o "$dest/operator.tar" "$operator"
if [[ $# == 2 ]]; then
  "$engine" save -o "$dest/builder.tar" localhost/enc-builder:3.13.3
  tar -czf "$dest/maven.tar.gz" -C "${ENC_MAVEN_CACHE:-$PWD/.runtime/plugin-maven}" .
  files+=(builder.tar maven.tar.gz)
fi
(cd "$dest" && sha256sum "${files[@]}" > SHA256SUMS)
