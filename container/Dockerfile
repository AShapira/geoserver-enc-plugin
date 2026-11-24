# Vanilla official GeoServer; only GDAL tooling and this plugin are added.
ARG GEOSERVER_IMAGE=docker.osgeo.org/geoserver:3.0.2
FROM ${GEOSERVER_IMAGE} AS plugin-build
COPY src/main /src
COPY portrayal/upstream /upstream
RUN mkdir -p /classes && javac --release 17 -cp '/usr/local/tomcat/webapps/geoserver/WEB-INF/lib/*' -d /classes /src/java/org/enc/geoserver/*.java \
    && cp -R /src/resources/. /classes/ && mkdir -p /classes/org/enc/geoserver/s52 \
    && cp /upstream/* /classes/org/enc/geoserver/s52/ && jar --create --file /tmp/gs-s57.jar -C /classes .
FROM ${GEOSERVER_IMAGE} AS service-base
USER root
ARG INSTALL_RUNTIME_PACKAGES=true
RUN case "$INSTALL_RUNTIME_PACKAGES" in \
    true) apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    gdal-bin python3-gdal python3-pil python3-requests ca-certificates curl fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* ;; \
    false) ;; \
    *) echo 'INSTALL_RUNTIME_PACKAGES must be true or false' >&2; exit 1 ;; esac
FROM service-base
RUN python3 -c 'from osgeo import gdal, ogr; from PIL import Image' \
    && ogrinfo --format S57 >/dev/null && ogrinfo --format GPKG >/dev/null \
    && ogrinfo --format SQLite >/dev/null && test -x /usr/bin/ogr2ogr \
    && command -v curl >/dev/null
COPY --from=plugin-build /tmp/gs-s57.jar /usr/local/tomcat/webapps/geoserver/WEB-INF/lib/gs-s57-0.4.0.jar
COPY scripts /opt/enc/scripts
COPY portrayal/upstream /opt/enc/portrayal/upstream
RUN chmod 755 /opt/enc/scripts/ogr_inland.py && python3 /opt/enc/scripts/inland_dictionary.py /usr/share/gdal /opt/enc/s57
COPY src/main/resources/org/enc/geoserver/cache-recipe.txt /opt/enc/src/main/resources/org/enc/geoserver/cache-recipe.txt
COPY viewer/enc.html /usr/local/tomcat/webapps/ROOT/enc.html
RUN mkdir -p /opt/enc-data /opt/enc-cache
ENV SKIP_DEMO_DATA=true EXTRA_JAVA_OPTS="-Xms512m -Xmx3g" ROOT_WEBAPP_REDIRECT=true
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 CMD curl -fsS 'http://127.0.0.1:8080/geoserver/ows?service=WMS&request=GetCapabilities&version=1.3.0' >/dev/null || exit 1
