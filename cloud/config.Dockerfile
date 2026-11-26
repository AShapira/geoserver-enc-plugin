ARG CLOUD_TAG
FROM docker.io/geoservercloud/geoserver-cloud-config:${CLOUD_TAG}
# Keep the release's routing and authentication filters for the viewer's static assets.
RUN for config in /etc/geoserver/gateway.yml /etc/geoserver/gateway-webflux.yml; do \
      [ -f "$config" ] || continue; \
      grep -Fq '${basepath}/webresources/wms/**' "$config" && \
      sed -i 's|${basepath}/webresources/wms/\*\*|${basepath}/webresources/wms/**,${basepath}/enc/viewer/**|' "$config" || exit 1; \
    done
