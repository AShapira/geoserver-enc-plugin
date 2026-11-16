#!/usr/bin/env bash
# Foreground demo server; Ctrl-C stops only this process.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
export GEOSERVER_HOME="$ENC_ROOT/.runtime/geoserver"
export GEOSERVER_DATA_DIR="$GEOSERVER_HOME/data_dir"
if [[ ! -f "$ENC_ROOT/target/gs-s57-0.1.0.jar" ]]; then
  echo 'Build first: scripts/build.sh' >&2; exit 1
fi
cp "$ENC_ROOT/target/gs-s57-0.1.0.jar" "$GEOSERVER_HOME/webapps/geoserver/WEB-INF/lib/"
export JETTY_OPTS="jetty.http.host=127.0.0.1 jetty.http.port=${ENC_PORT:-18080}"
export JAVA_OPTS="-Xms256m -Xmx1536m ${JAVA_OPTS:-}"
exec bash "$GEOSERVER_HOME/bin/startup.sh"
