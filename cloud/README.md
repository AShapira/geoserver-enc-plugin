# Built-in S-57 support for GeoServer Cloud

Build the plugin independently for each Cloud release. The Cloud POMs pin GeoServer **3.0.0-CLOUD / GeoTools 35.0** and **3.0.2-CLOUD / GeoTools 35.2**. Both use JDK 25. The standalone plugin archives target different GeoServer artifacts. [3.0.0 dependencies](https://github.com/geoserver/geoserver-cloud/blob/v3.0.0/src/pom.xml) · [3.0.2 dependencies](https://github.com/geoserver/geoserver-cloud/blob/v3.0.2/src/pom.xml)

## Integrate with a Cloud distribution

Run the following in the ENC checkout, once for each tag, using a fresh Cloud checkout. The integration script installs a release-managed Maven module alongside the vector input formats and adds it as a dependency of the vector-format module. The input-format starter brings the module into the applications. It also adds native GDAL to the shared GeoServer application base image. The GeoTools SPI files provide store, filter function and external graphic discovery. Spring Boot discovers the existing ENC configuration through its imports file. The configuration registers the scale callback on WMS-capable classpaths, including GWC's internal renderer.

```bash
tag=3.0.0    # repeat with 3.0.2
checkout="$(mktemp -d)/geoserver-cloud"
git clone --branch "v$tag" --depth 1 --recurse-submodules https://github.com/geoserver/geoserver-cloud "$checkout"
python3 cloud/integrate.py "$checkout"
(cd "$checkout"
 if [ "$tag" = 3.0.2 ]; then make deps; fi
 make install
 make build-image
)
```

Cloud 3.0.0 resolves patched GeoServer artifacts using the repository configured by its parent POM. Cloud 3.0.2 builds the pinned GeoServer submodule locally. The 3.0.0 registry returned HTTP 401 in this environment. To build those artifacts locally, clone the matching `3.0.0-CLOUD` source distribution with its submodule, then run `make install` there using the same Maven repository as the Cloud build. [Tagged GeoServer dependency distribution](https://github.com/camptocamp/geoserver-cloud-geoserver/tree/3.0.0-CLOUD)

Use the build tools and image repository settings documented by the corresponding tag. Give the derived distribution its own image names. [3.0.0 build instructions](https://github.com/geoserver/geoserver-cloud/blob/v3.0.0/docs/src/developer-guide/build_instructions.md) · [3.0.2 build instructions](https://github.com/geoserver/geoserver-cloud/blob/v3.0.2/docs/src/developer-guide/build_instructions.md)

| Service | S-57 responsibilities |
| --- | --- |
| REST | Discover stores, inspect feature types and publish. Enable `-Denc.installStyles=true` on one writer instance. |
| Web UI | Discover and configure the datastore, preview schemas and list installed styles. |
| WFS | Open the datastore and serve chart features. |
| WMS and GWC | Read the same chart and cache paths, resolve styles and render directly. GWC uses its own internal WMS machinery. |
| Gateway, configuration and discovery | Use the tagged configuration with the viewer path added to the WMS gateway route. |

Give each datastore consumer the same absolute read-only chart path and writable cache path. Share the catalogue and style resource store across replicas. Use `-Denc.installStyles=false` on readers. The display name for the GeoTools vector-format filter is `S-57 ENC (GDAL)`. The default filter admits new factories. Sites with an explicit disable rule can set `geotools.data.filtering.vector-formats.[S-57 ENC (GDAL)]` to true. When automatic tile-layer creation is disabled or the published layer is missing from GWC, register the tile layer explicitly before requesting WMTS. The installation checker exercises this case.

## Open the ENC viewer

The service JAR includes the viewer at `<public-base>/enc/viewer/index.html`. The integration script adds `${basepath}/enc/viewer/**` to the existing WMS route's Path predicate in the gateway configuration. Apply the same path to any site-managed gateway configuration and retain its filters, including shared authentication and base-path stripping. The reference build applies this edit to the tagged configuration image. With the example below, open `http://127.0.0.1:18800/geoserver/cloud/enc/viewer/index.html`. The WMS service supplies the page and OpenLayers, WFS serves feature search, and GWC supplies advertised tiles.

## Qualify the published service images

For a downstream operator the included Docker build compiles the same Java sources against the target WMS image's exact libraries using JDK 25. It bakes that JAR into each application's `BOOT-INF/lib` and classpath index, installs native GDAL, and disables the upstream JVM cache trained on the original classpath. This also works with 3.0.0's `JarLauncher`. Cloud 3.0.2 additionally supports `/opt/additional_libs` through `PropertiesLauncher`. [3.0.0 launcher](https://github.com/geoserver/geoserver-cloud/blob/v3.0.0/src/apps/base-images/spring-boot/Dockerfile) · [3.0.2 launcher](https://github.com/geoserver/geoserver-cloud/blob/v3.0.2/src/apps/base-images/spring-boot/Dockerfile)

Use a fresh Compose project and volumes for each tag. Supply a local directory containing NOAA US5NY1AI.000 and its .001 update. The acceptance script creates the `enc_check` workspace, publishes a depth-area layer, reads features, compares both renderers, checks fresh and cached tiles, inspects the applied update, restarts one writer and renderer, and repeats the checks. It requires Python 3 and Pillow on the host. Provide the three passwords through the environment.

```bash
export CONTAINER_ENGINE=podman CLOUD_TAG=3.0.0 ENC_PORT=18800
export ENC_CHARTS=/absolute/path/to/US5NY1AI
: "${GEOSERVER_PASSWORD:?}" "${RABBITMQ_PASSWORD:?}" "${POSTGRES_PASSWORD:?}"
export GEOSERVER_PASSWORD RABBITMQ_PASSWORD POSTGRES_PASSWORD
project="enc-check-${CLOUD_TAG//./}"
cloud/build.sh "$CLOUD_TAG"
compose=("$CONTAINER_ENGINE" compose -p "$project" -f cloud/compose.yml)
"${compose[@]}" run --rm init-volumes
"${compose[@]}" up -d --scale wms=2 gateway rest wms wfs webui gwc
python3 cloud/check.py --tag "$CLOUD_TAG" --project "$project" \
  --url "http://127.0.0.1:$ENC_PORT/geoserver/cloud" --require-miss
"${compose[@]}" down
```

Repeat with `CLOUD_TAG=3.0.2`, a separate project and port. Startup includes database initialization and registration of 1,530 styles. [Validation results](../docs/plugin-install-validation.json)
