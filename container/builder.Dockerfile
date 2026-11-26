FROM ghcr.io/osgeo/gdal:ubuntu-full-3.13.3@sha256:2dd0f81ef927ff4c3d4dbe4f73c029dc86d4073974c0564f8e196f6e1412e2e0
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends openjdk-21-jdk-headless maven python3-pil && rm -rf /var/lib/apt/lists/*
RUN javac -version && mvn -version && ogrinfo --format S57 && ogrinfo --format GPKG && ogrinfo --format SQLite
WORKDIR /work
