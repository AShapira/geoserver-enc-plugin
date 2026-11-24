# Kartoza GeoServer 2.28.0: build, installation and offline use

Prepared by Codex. Validation date: 2026-11-17.

To deploy the multi-source viewer with named providers, shared styles, and verified WMS/WMTS groups, use the [full offline transfer](airgap-deployment.md) or the [online publishing guide](publishing-guide.md). This manual covers the Kartoza 2.28.0 image layout, its single-cell or prepared-catalogue store and its optional publisher.

The deployment ZIP includes the Python helpers and two main build paths. Its root Dockerfile adds the plugin JAR to a prepared vendor image. The [plugin build manual](../airgap/README.md) describes its base image requirements.

The S-57 plugin builds and runs with `docker.io/kartoza/geoserver:2.28.0`.
Use `container/kartoza.Dockerfile` for this image. It compiles against the base
image's actual libraries and does not install packages or download dependencies.
The full chart-service recipe in `container/Dockerfile` uses the official GeoServer 3.0.2 image. Its offline build uses the prepared service base described in the kit’s root README.

## Build with no network

With the base image already loaded into the local engine, run from the repository root:

```bash
# Docker: --pull=false uses the local base. --network=none blocks RUN networking.
docker build --pull=false --network=none --no-cache \
  -f container/kartoza.Dockerfile -t geoserver-s57:2.28.0 .

# Podman: --pull=never also prohibits fetching a missing base image.
podman build --pull=never --network=none --no-cache --format docker \
  -f container/kartoza.Dockerfile -t localhost/geoserver-s57:2.28.0 .
```

The Podman command was executed successfully with no build cache. No host JDK,
Maven, Python, package repository, or internet access is needed for this build.
Docker syntax is provided for users of Docker; the executed validation used
Podman on Linux x86_64. Other architectures have not been tested.

To export only the JAR with Docker BuildKit:

```bash
docker build --pull=false --network=none --target artifact \
  --output type=local,dest=dist/kartoza-2.28.0 \
  -f container/kartoza.Dockerfile .
```

For transfer into an air-gapped environment, save the base image on the connected
machine, transfer its archive and the source checkout, then load the archive:

```bash
# Connected machine; choose Docker or Podman consistently.
docker pull kartoza/geoserver:2.28.0
docker save -o kartoza-geoserver-2.28.0.tar kartoza/geoserver:2.28.0

# Disconnected machine.
docker load -i kartoza-geoserver-2.28.0.tar
```

Retain the image digest and file checksums with the transferred files. The tested
base digest and artifact hashes are recorded in `docs/kartoza-2.28.0-validation.json`.
Changing only the base tag is a way to attempt a new target build, not proof of
compatibility with that other version.

## Dependencies

| Operation | Dependencies | Supplied by this Kartoza base? |
| --- | --- | --- |
| Compile/package plugin | JDK 17 `javac` and `jar`; shell, `mkdir`, `cp` | Yes |
| Java compilation/runtime | GeoServer 2.28.0, GeoTools 34.0 including GeoPackage/JDBC support and their transitive libraries; Tomcat servlet libraries | Yes; used directly, never replaced |
| Read S-57 at runtime | GDAL `ogr2ogr`, S57/GPKG/SQLite drivers, GDAL dictionaries and PROJ data | Yes; GDAL 3.8.4 tested |
| Source/resource inputs | `src/main/java`, `src/main/resources`, and the pinned XML/PNG assets in `portrayal/upstream` | In the source checkout |
| Prepare catalogues | Python 3 and GDAL Python bindings, local ENC source data | Python/GDAL supplied; chart data must be provided |
| Publish chart groups with shared styles | Python 3, GDAL Python bindings, bundled style library, REST credentials and writable chart cache | Yes |
| Java test suite | Test sources, JUnit Platform Console Standalone 1.11.4, real ENC fixtures for native tests | JUnit and fixtures must be supplied separately |
| Python/image service tests | Python test sources, Pillow, ENC fixtures, running GeoServer | Pillow and fixtures must be supplied separately |

The extension invokes GDAL in a separate process. GeoServer's GDAL raster plugin
and GDAL Java/JNI bindings are not required by this extension. GeoTools' GeoPackage,
SQLite JDBC, JTS and other server libraries remain the versions supplied by the
target server. Do not copy the Maven dependency tree into `WEB-INF/lib`.

**Base image plus source is sufficient to build the plugin and runtime image.**
Full style generation additionally needs Pillow; testing also needs test tools
and real chart data. These are separate from compiling the extension.

For optional image tests, prepare a Pillow wheel matching the container's Python
version and architecture. The tested base uses Python 3.12; validation used the
Pillow 11.3.0 CPython 3.12 Linux x86_64 wheel. After copying it into the container,
it can be extracted without installing `pip`:

```bash
docker cp /path/to/pillow-wheel.whl geoserver-s57:/tmp/pillow.whl
docker exec geoserver-s57 python3 -m zipfile -e /tmp/pillow.whl /opt/enc/python
docker exec -e PYTHONPATH=/opt/enc/python geoserver-s57 \
  python3 -c 'from PIL import Image; print(Image.__version__)'
```

For a durable deployment, perform the same extraction in a derived image using
the transferred wheel, or transfer an image with Pillow already included.
Container-local changes made by `docker exec` are lost on recreation.

## Run and publish

For a fresh isolated instance, set `GEOSERVER_ADMIN_PASSWORD` in the host environment, then substitute the absolute host path to your extracted exchange in the bind mount. For the optional publisher, export `GEOSERVER_PASSWORD="$GEOSERVER_ADMIN_PASSWORD"` before invoking the wrapper. Use the same engine and tag throughout. The Docker example uses `geoserver-s57:2.28.0`. For the Podman build above, use `podman` and `localhost/geoserver-s57:2.28.0`.

```bash
docker run --pull=never -d --name geoserver-s57 \
  -p 127.0.0.1:18081:8080 \
  -e GEOSERVER_ADMIN_USER=admin \
  -e GEOSERVER_ADMIN_PASSWORD \
  -e INITIAL_MEMORY=512M -e MAXIMUM_MEMORY=2G -e SAMPLE_DATA=false \
  --mount type=volume,src=geoserver-s57-228-data,dst=/opt/geoserver/data_dir \
  --mount type=bind,src=/absolute/path/to/enc,dst=/enc,readonly \
  geoserver-s57:2.28.0
```

Keep base `.000` files and all of their numbered updates together. Use
container-visible paths. Kartoza manages permissions for its data directory;
`/opt/geoserver/data_dir/enc-cache` is a suitable persistent cache location.
Keep forced extension downloads disabled in an offline deployment.

Open `http://localhost:18081/geoserver/`. Under **Stores → Add new Store**,
choose **S-57 ENC (GDAL)**. Set `file=/enc/YOUR_CELL.000`,
`cache=/opt/geoserver/data_dir/enc-cache` and `ogr2ogr=/usr/bin/ogr2ogr`.
For a prepared catalogue, set `catalogue=/enc/catalogue.sqlite` instead of `file`.
Publish individual classes using the installed global ENC styles, or assemble a chart group with the bundled publisher:

```bash
docker exec \
  -e GEOSERVER_PASSWORD \
  geoserver-s57 bash /opt/enc/publish.sh \
  /enc/YOUR_CELL.000 --workspace noaa --palette day
```

`/opt/enc/publish.sh` supplies Kartoza's paths and localhost URL, and switches from
root to the same service account as Kartoza's entrypoint (`geoserveruser` by
default, or the image's `USER` environment setting). This prevents root-owned
style directories, which otherwise cause REST `Error writing style` failures.
It defaults generated output to the writable data directory. Additional
publisher arguments override the defaults. Use `--update` only for an existing
plugin-owned workspace; pass `--palette dusk` or `--palette night` for other groups.

For an existing deployment, retain its configuration and data mounts, switch its
image to the built image, and recreate the service. Alternatively, copy only the
version-matched plugin JAR into
`/usr/local/tomcat/webapps/geoserver/WEB-INF/lib/`, then restart GeoServer. Do not
mount an entire replacement `WEB-INF/lib` directory. A derived image preserves
the installation across container recreation.

## Maven alternative

```bash
mvn -Pgeoserver-2.28 package
```

This profile selects GeoServer **2.28.0**, GeoTools **34.0**, and **`gs-wms`**.
GeoServer 3.0 renamed the WMS dependency to **`gs-wms-core`**; merely changing
the version number of that artifact is insufficient. The default profile retains
GeoServer 3.0.2 / GeoTools 35.2 / `gs-wms-core`.

Maven needs a JDK, Maven itself, all dependency JARs/POMs and build plugins in its
local repository or an accessible internal repository. A Docker base image does
not populate Maven's repository. After a complete connected build, this was also
verified successfully with the populated local Maven cache:

```bash
mvn -o -Pgeoserver-2.28 -DskipTests package
```

Run native tests with `S57_TEST_FILE`, `OGR2OGR`, and optionally `S57_CATALOGUE`
set as described in the main README. Without those inputs, native tests are
skipped. Use the versioned artifact under `dist/kartoza-2.28.0` for this target;
the existing `scripts/package.py` is still the 3.0.2 demo packager.

## Executed validation

- Cold image builds with `--pull=never --network=none --no-cache` succeeded.
- GeoServer started in a fresh container with `--network none`, no host mounts
  and no published ports. The existing national demo was not changed.
- REST reported GeoServer 2.28.0, GeoTools 34.0 and GeoWebCache 1.28.0;
  the container runs Temurin 17.0.16 and GDAL 3.8.4.
- All **28 Java tests passed, none skipped**, compiled and executed inside the
  actual Kartoza runtime against its installed plugin and server libraries.
  These cover SPI discovery, read-only access, filtering/paging, native updates,
  missing-update rejection, cache reuse, scale handling and edge metadata.
- The complete 7,114-cell inventory was used for the Java catalogue discovery
  test. Only source cells intersecting the test query were copied into the
  isolated container; this was not a complete national reimport.
- All **15 Python tests passed** with the container's GDAL bindings and the
  separately supplied Pillow wheel.
- Maven's 2.28 profile passed all **28 tests with no skips**, using the host's
  isolated Java 21/GDAL 3.11.5 toolchain. The subsequent offline package check
  used the populated Maven cache and skipped execution of tests.
- The default GeoServer 3.0.2 Maven configuration also passed all 28 tests after
  adding the 2.28 profile.
- Single-cell and two-cell catalogue publications passed day/dusk/night WMS,
  WFS and WMTS smoke checks: WMS 1.1.1 and axis-correct 1.3.0 pixels matched;
  EPSG:3857 and detail renders worked; four concurrent renders matched; repeated
  WMTS tiles were identical and returned cache HIT; WFS returned split soundings.
- The smoke test now accepts `--bbox WEST SOUTH EAST NORTH` and derives its
  axis-order checks from the actual request region, rather than worldwide
  catalogue bounds.
- An additional 1800×1800 WMS image rendered both cells in their expected
  quadrants; WFS returned 1,730 soundings with both cell identifiers. The blank
  quadrants lie outside the two supplied cells' coverage.
- The publisher wrapper was invoked as root against a new workspace using
  US5NY1AI plus its `.001` update. Style files were owned by `geoserveruser`, the
  cache reported applied update 1, and its complete day-palette service smoke
  check passed. Seven service suites passed in total.
- The delivered JAR's uncompressed entries were checked byte-for-byte against
  the JAR exercised by the container tests; only ZIP timestamps differ.

Machine-readable results are in `docs/kartoza-2.28.0-validation.json`. Local raw
logs, fixtures and images are retained under `.runtime/kartoza-2.28.0/`.
The build used the current working tree, including pre-existing uncommitted
portrayal changes; those edits were preserved, not attributed to this work.
No Java production-source compatibility changes were needed.

This validates the tested image and data paths. It does not establish S-52/ECDIS
conformance, every ENC cell, a full national load test on 2.28.0, other CPU
architectures, or other GeoServer versions.
