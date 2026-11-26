# One-shot chart administration jobs share the server's exact GDAL and Java libraries.
ARG GEOSERVER_IMAGE=docker.osgeo.org/geoserver:3.0.2-gdal
FROM ${GEOSERVER_IMAGE}
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3-pil python3-requests && rm -rf /var/lib/apt/lists/*
COPY scripts /opt/enc/scripts
COPY portrayal/upstream /opt/enc/portrayal/upstream
COPY src/main/resources/org/enc/geoserver/cache-recipe.txt /opt/enc/src/main/resources/org/enc/geoserver/cache-recipe.txt
RUN python3 -c 'from osgeo import ogr; from PIL import Image' && command -v ogr2ogr && chmod +x /opt/enc/scripts/ogr_inland.py
ENTRYPOINT ["python3"]
CMD ["/opt/enc/scripts/deployment.py"]
