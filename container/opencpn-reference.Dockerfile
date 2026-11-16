# Isolated reference viewer; it is not part of the GeoServer runtime image.
FROM docker.io/library/ubuntu:26.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    opencpn xvfb xdotool openbox imagemagick x11-utils python3 python3-pil ca-certificates dbus-x11 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
ENV DISPLAY=:99
CMD ["sleep", "infinity"]
