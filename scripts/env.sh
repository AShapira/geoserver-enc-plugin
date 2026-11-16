#!/usr/bin/env bash
# Source from the repository, or from another script. Local runtime only.
ENC_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export JAVA_HOME="$ENC_ROOT/.runtime/env"
export PATH="$JAVA_HOME/bin:$PATH"
export PROJ_DATA="$JAVA_HOME/share/proj"
export GDAL_DATA="$JAVA_HOME/share/gdal"
