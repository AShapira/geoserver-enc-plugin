# Offline build: load the base image locally, then build with --network=none.
# Use --pull=never with Podman. No package manager or Maven downloads are used.
ARG GEOSERVER_IMAGE=docker.io/kartoza/geoserver:2.28.0
FROM ${GEOSERVER_IMAGE} AS plugin-build
USER root
COPY src/main /src
COPY portrayal/upstream /upstream
RUN mkdir -p /classes/org/enc/geoserver/s52 \
    && javac --release 17 \
       -cp '/usr/local/tomcat/webapps/geoserver/WEB-INF/lib/*:/usr/local/tomcat/lib/*' \
       -d /classes /src/java/org/enc/geoserver/*.java \
    && cp -R /src/resources/. /classes/ \
    && cp /upstream/* /classes/org/enc/geoserver/s52/ \
    && jar --create --file /tmp/gs-s57-0.2.0.jar -C /classes .

# Optional Docker BuildKit --target artifact --output type=local,dest=dist/kartoza.
FROM scratch AS artifact
COPY --from=plugin-build /tmp/gs-s57-0.2.0.jar /gs-s57-0.2.0.jar

FROM ${GEOSERVER_IMAGE} AS runtime
USER root
RUN test -x /usr/bin/ogr2ogr \
    && ogrinfo --format S57 >/dev/null \
    && ogrinfo --format GPKG >/dev/null \
    && ogrinfo --format SQLite >/dev/null
COPY --from=plugin-build /tmp/gs-s57-0.2.0.jar /usr/local/tomcat/webapps/geoserver/WEB-INF/lib/gs-s57-0.2.0.jar
# Helpers are supplied for use when their optional Python dependencies are available.
COPY scripts /opt/enc/scripts
COPY container/publish-kartoza.sh /opt/enc/publish.sh
COPY portrayal/upstream /opt/enc/portrayal/upstream
COPY src/main/resources/org/enc/geoserver/cache-recipe.txt /opt/enc/src/main/resources/org/enc/geoserver/cache-recipe.txt
# Kartoza retains control of users, permissions, heap options and startup.
# Put writable ENC caches under GEOSERVER_DATA_DIR or supply a writable volume.
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 CMD curl -fsS 'http://127.0.0.1:8080/geoserver/ows?service=WMS&request=GetCapabilities&version=1.3.0' >/dev/null || exit 1
