# S-57 extension: lean offline image build

Prepared by Codex. Package revision 1, 2026-11-18.

This source-only kit adds the S-57 extension to an existing GeoServer image.
The default target is **kartoza/geoserver:2.28.0 / GeoTools 34.0**. Its Dockerfile
compiles against the libraries inside your chosen base image, then adds one JAR.
The final image inherits the base's user, entrypoint, command and environment.

## What to bring into the air gap

1. This extracted package.
2. The complete base image, already loaded into Docker or Podman.
3. A working Linux-container engine for that image's architecture.

The base image must contain:

- **JDK 17 or 21**, with `javac` and `jar` on PATH. A JRE alone is insufficient.
- An unpacked GeoServer web application, including its own matching GeoTools
  GeoPackage/JDBC dependencies, and servlet libraries.
- GDAL's **ogr2ogr and ogrinfo**, with **S57, GPKG and SQLite** drivers, GDAL
  dictionaries and PROJ data available to the runtime user.
- A POSIX shell and the ordinary `chmod` utility used during the build.

Kartoza 2.28.0 already supplies these dependencies. No host Java, Maven, Python,
Pillow, JUnit, C compiler, package manager or network repository is required.
Chart files are not needed to build the image; supply them when using the store.

If the base lacks a dependency, prepare and transfer a suitable base image
beforehand. This package neither downloads dependencies nor adds a second toolchain.
In particular, the inspected vanilla `docker.osgeo.org/geoserver:3.0.2` image
contains Java and GeoPackage support but **does not contain GDAL**.

## Build

Extract the ZIP and open a terminal in the extracted directory containing
`Dockerfile`, `src` and `portrayal`. The build context is this directory, not its parent.

```bash
docker build --pull=false --network=none --no-cache -t geoserver-s57:2.28.0 .
```

Or with Podman, which can explicitly refuse all pulls:

```bash
podman build --pull=never --network=none --no-cache --format docker -t localhost/geoserver-s57:2.28.0 .
```

Both commands also work as single lines in PowerShell. Docker's `--pull=false`
does not prevent fetching a missing base, so load the image first. No external
Dockerfile frontend is requested. `--network=none` blocks build-step networking;
the package performs no downloads. A missing dependency causes a build error.

For transfer, use `docker save` on the connected machine and `docker load` on
the disconnected machine, or the equivalent Podman commands. The image archive
is separate from this small source kit. `SHA256SUMS` lists every kit input's
checksum; on Linux, run `sha256sum -c SHA256SUMS` before building.

## Use another base image

| Build argument | Default | Purpose |
| --- | --- | --- |
| `GEOSERVER_IMAGE` | `docker.io/kartoza/geoserver:2.28.0` | Locally available base image or digest |
| `GEOSERVER_VERSION` | `2.28.0` | Expected exact version; checked against `gs-main-VERSION.jar` |
| `GEOSERVER_LIB_DIR` | `/usr/local/tomcat/webapps/geoserver/WEB-INF/lib` | Compile libraries and plugin installation directory |
| `SERVLET_LIB_DIR` | `/usr/local/tomcat/lib` | Additional servlet/container libraries for compilation |
| `OGR2OGR` | `ogr2ogr` | GDAL executable checked at image build time |
| `OGRINFO` | `ogrinfo` | GDAL driver-inspection executable checked at image build time |

Example for a pre-equipped GeoServer 3.0.2 image:

```bash
docker build --pull=false --network=none --no-cache \
  --build-arg GEOSERVER_IMAGE=my-geoserver-with-jdk-and-gdal:3.0.2 \
  --build-arg GEOSERVER_VERSION=3.0.2 \
  -t geoserver-s57:3.0.2 .
```

Change the library-directory arguments if your image uses different paths.
`OGR2OGR` selects the executable checked at build time; configure that same path
in the GeoServer store at runtime. The GDAL environment remains the base image's
responsibility. The Dockerfile does not change the service account, data directory,
ports, passwords, heap flags, startup extensions or health check.

**The build recipe is configurable; the resulting JAR is version-specific.**
Always rebuild for the target image and validate it. GeoServer 2.28.0 / GeoTools
34.0 and 3.0.2 / 35.2 are the project's tested Java targets. Other releases,
layouts and architectures are not automatically compatible. A differently
packaged deployment, such as GeoServer Cloud services or a WAR unpacked only
at startup, may require an adapted installation recipe.

## Run and check the extension

Use the resulting image in your existing deployment configuration. Keep that
image vendor's settings, data mounts and service-account rules. For a separate
Kartoza test instance, replace the source path and password:

```bash
docker run -d --name geoserver-s57 \
  -p 127.0.0.1:18081:8080 \
  -e GEOSERVER_ADMIN_USER=admin \
  -e GEOSERVER_ADMIN_PASSWORD='replace-this-password' \
  -e INITIAL_MEMORY=512M -e MAXIMUM_MEMORY=2G -e SAMPLE_DATA=false \
  --mount type=volume,src=geoserver-s57-data,dst=/opt/geoserver/data_dir \
  --mount type=bind,src=/absolute/path/to/enc,dst=/enc,readonly \
  geoserver-s57:2.28.0
```

Those environment variables and data paths are **Kartoza-specific**, not universal
GeoServer settings. Keep any forced extension downloads disabled when offline.
If your base changes its web-application directory during startup, ensure the
installed JAR remains in the active application's `WEB-INF/lib`.

Open `http://localhost:18081/geoserver/`, then choose
**Stores → Add new Store → S-57 ENC (GDAL)**:

| Store setting | Kartoza example |
| --- | --- |
| `file` | `/enc/YOUR_CELL.000` |
| `catalogue` | Leave empty for a single cell; alternatively use a prepared `catalogue.sqlite` and leave `file` empty |
| `cache` | `/opt/geoserver/data_dir/enc-cache` |
| `ogr2ogr` | `/usr/bin/ogr2ogr` |
| `timeout` | `300` seconds |

Keep the base `.000` and all numbered updates together. Paths are inside the
container; the service account must read the sources and write the cache.
Publish an object class, apply an appropriate GeoServer style and check WMS/WFS.
GDAL drivers can be checked with `docker exec geoserver-s57 ogrinfo --formats`.

## Package contents and scope

- Java production sources and service/Spring/cache resources required by the plugin.
- The pinned S-52 lookup XML and three symbol atlases required by Java at runtime.
- One Dockerfile, build-context exclusions, this manual, checksums and license/provenance notices.

There is **no prebuilt JAR**, Maven project, test suite, Python environment,
publisher, catalogue-preparation tool, demo, viewer, chart data or performance
evidence. Those are not required to build or install the extension. This kit
does not automatically create a styled nautical chart group. Use GeoServer's
ordinary styles or bring pre-generated SLDs and their referenced assets separately.
The full project's chart-style publisher remains a separate workflow and needs
Python/GDAL bindings plus Pillow. Portrayal remains experimental; no ECDIS or
complete S-52 conformance is claimed.

## Checks performed for this kit

On 2026-11-18, the extracted kit built with Podman on Linux x86_64, with
`--pull=never --network=none --no-cache`, against both Kartoza 2.28.0 and the
project's existing official-GeoServer-3.0.2-based image with GDAL already installed.
The inspected vanilla official 3.0.2 image compiled the Java sources, then was
correctly rejected for missing GDAL. An intentionally wrong GeoServer version
was also rejected. Other architectures and vendor images have not been tested.

The Kartoza build's JAR entries exactly match the previously validated plugin's
classes and resources; ZIP timestamps are irrelevant to that comparison. All
base runtime settings were preserved. A fresh lean-image container started
without networking, discovered the S-57 store, applied a real `.001` update,
returned WFS soundings and rendered a nonblank WMS image using a standard style.
No publisher or Python image library was installed for those service checks.
