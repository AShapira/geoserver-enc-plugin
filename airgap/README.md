# Install a release-matched standalone S-57 plugin

Each `geoserver-VERSION-s57-plugin.zip` contains a single plugin JAR at its root and the license notices. Match the complete GeoServer version. The plugin includes its Java SPI registrations, S-52 resources and style library. Each server needs its matching GeoTools GeoPackage libraries, executable GDAL with S57, GPKG and SQLite drivers, GDAL dictionaries, PROJ data and a cache writable by the service account.

For GeoServer 3.0.2 use the official GDAL-enabled image. Add the following to the existing container definition and recreate it with its existing data volume. Keep existing community extension names in the comma-separated list. Preserve the current download policy for other extensions. For a fully local install stage their ZIPs alongside S-57 and set `INSTALL_EXTENSIONS=false`.

```yaml
image: docker.osgeo.org/geoserver:3.0.2-gdal
environment:
  COMMUNITY_EXTENSIONS: s57
  INSTALL_EXTENSIONS: 'false'
volumes:
  - ./dist/geoserver-3.0.2-s57-plugin.zip:/opt/additional_libs/geoserver-3.0.2-s57-plugin.zip:ro
```

Run `container/build-plugins.sh` to produce both releases in Docker or Podman. The builder pins GDAL 3.13.3 and uses JDK 21 and Maven. The runtime GDAL version follows the installed server. For an unpacked WAR, stop the server, replace the old S-57 JAR in `WEB-INF/lib` with the one from the matching archive, and restart. See [Kartoza 2.28.0](../docs/kartoza-2.28.0.md) for its different startup convention or the [offline transfer guide](../docs/airgap-deployment.md).

The plugin includes the ENC viewer and search demo at `<geoserver-base>/enc/viewer/index.html`. Publish a feature type from an S-57 datastore, then open the viewer. Its map library and service requests use the same GeoServer installation.
