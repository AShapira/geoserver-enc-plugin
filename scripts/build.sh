#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$ENC_ROOT"
export OGR2OGR="$JAVA_HOME/bin/ogr2ogr"
mvn -B package
python -m unittest discover -s tests -v
