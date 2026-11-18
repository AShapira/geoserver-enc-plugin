# No downloads. The base image must already exist in the local image store.
ARG GEOSERVER_IMAGE=docker.io/kartoza/geoserver:2.28.0
ARG GEOSERVER_VERSION=2.28.0
ARG GEOSERVER_LIB_DIR=/usr/local/tomcat/webapps/geoserver/WEB-INF/lib
ARG SERVLET_LIB_DIR=/usr/local/tomcat/lib
ARG OGR2OGR=ogr2ogr
ARG OGRINFO=ogrinfo

FROM ${GEOSERVER_IMAGE} AS plugin-build
USER root
ARG GEOSERVER_VERSION
ARG GEOSERVER_LIB_DIR
ARG SERVLET_LIB_DIR
COPY src/main/java /src
COPY src/main/resources /classes
COPY portrayal/upstream /classes/org/enc/geoserver/s52
RUN set -eu; \
    command -v javac >/dev/null || { echo 'Base image requires a JDK with javac (Java 17 or 21).' >&2; exit 1; }; \
    command -v jar >/dev/null; \
    test -f "${GEOSERVER_LIB_DIR}/gs-main-${GEOSERVER_VERSION}.jar" || { echo 'GeoServer version or library directory does not match the base image.' >&2; exit 1; }; \
    set -- "${GEOSERVER_LIB_DIR}"/gt-geopkg-*.jar; \
    test "$#" -eq 1 && test -f "$1" || { echo 'Base image must contain matching GeoTools GeoPackage support.' >&2; exit 1; }; \
    javac --release 17 -cp "${GEOSERVER_LIB_DIR}/*:${SERVLET_LIB_DIR}/*" \
      -d /classes /src/org/enc/geoserver/*.java; \
    jar --create --file /tmp/gs-s57-0.2.0.jar -C /classes .; \
    chmod 644 /tmp/gs-s57-0.2.0.jar

# This stage inherits the original user, entrypoint, command and environment.
FROM ${GEOSERVER_IMAGE} AS runtime
ARG GEOSERVER_LIB_DIR
ARG OGR2OGR
ARG OGRINFO
RUN set -eu; \
    for installed in "${GEOSERVER_LIB_DIR}"/gs-s57*.jar; do \
      test -f "$installed" || continue; \
      test "$installed" = "${GEOSERVER_LIB_DIR}/gs-s57-0.2.0.jar" \
        || { echo 'Base contains another S-57 plugin JAR; use a prepared base without an older installation.' >&2; exit 1; }; \
    done; \
    command -v "$OGR2OGR" >/dev/null && command -v "$OGRINFO" >/dev/null \
      || { echo 'Base image needs GDAL ogr2ogr/ogrinfo; prepare it before entering the air gap.' >&2; exit 1; }; \
    "$OGR2OGR" --version; \
    "$OGRINFO" --format S57 >/dev/null; \
    "$OGRINFO" --format GPKG >/dev/null; \
    "$OGRINFO" --format SQLite >/dev/null
COPY --from=plugin-build /tmp/gs-s57-0.2.0.jar ${GEOSERVER_LIB_DIR}/gs-s57-0.2.0.jar
