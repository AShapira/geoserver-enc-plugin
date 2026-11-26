# Downstream release check using the same exploded Spring Boot layout as the tagged app.
ARG CLOUD_TAG=3.0.0
ARG SERVICE=wms
FROM docker.io/geoservercloud/geoserver-cloud-wms:${CLOUD_TAG} AS api
FROM docker.io/library/eclipse-temurin:25-jdk AS compiler
COPY --from=api /opt/app/bin/BOOT-INF/lib /api
COPY src/main /src
COPY portrayal/upstream /portrayal
RUN mkdir -p /classes/org/enc/geoserver/s52 && javac --release 17 -cp '/api/*' -d /classes /src/java/org/enc/geoserver/*.java && cp -R /src/resources/. /classes/ && cp /portrayal/* /classes/org/enc/geoserver/s52/ && jar cf /gs-s57.jar -C /classes .
FROM docker.io/geoservercloud/geoserver-cloud-${SERVICE}:${CLOUD_TAG}
USER root
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gdal-bin && rm -rf /var/lib/apt/lists/* && ogrinfo --format S57 && ogrinfo --format GPKG && ogrinfo --format SQLite
COPY --from=compiler /gs-s57.jar /opt/app/bin/BOOT-INF/lib/gs-s57.jar
RUN echo '- "BOOT-INF/lib/gs-s57.jar"' >> /opt/app/bin/BOOT-INF/classpath.idx
# The upstream cache was trained against a different classpath.
ENV AOT_MODE=off
