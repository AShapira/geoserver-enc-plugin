# S-57 extension: lean offline image build

Release **0.4.0**.

The root Dockerfile in this kit adds the S-57 extension to an existing GeoServer image.
The default target is **kartoza/geoserver:2.28.0 / GeoTools 34.0**. Its Dockerfile
compiles against the libraries inside your chosen base image, then adds one JAR.
The final image inherits the base's user, entrypoint, command and environment.
This kit is maintained on `main`; no vendor-specific source branch is needed.
The release archive is `gs-s57-0.4.0-airgap-build.zip`.

Use this recipe for the plugin-enabled vendor image. For the complete viewer and publishing service, start with the extracted ZIP’s root README or the [deployment manual](../docs/airgap-deployment.md). The full service uses `container/Dockerfile`.

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
- A clean extension installation: no older `gs-s57*.jar` beside the new plugin.
  A base already containing `gs-s57-0.4.0.jar` is supported; it is replaced.

Kartoza 2.28.0 already supplies these dependencies. No host Java, Maven, Python,
Pillow, JUnit, C compiler, package manager or network repository is required.
The JAR includes the compiled ENC style library. The first GeoServer startup installs all three palettes before any charts are supplied.

If the base lacks a dependency, prepare and transfer a suitable base image
beforehand. This package neither downloads dependencies nor adds a second toolchain.
In particular, the inspected vanilla `docker.osgeo.org/geoserver:3.0.2` image
contains Java and GeoPackage support but **does not contain GDAL**.

For runtime use, the server needs Java 17 or 21, the native shared libraries
required by its GDAL/PROJ installation, and its matching GeoServer libraries
(including GeoTools GeoPackage/JDBC, SQLite JDBC and JTS). Keep those supplied
versions together; do not assemble a mixture of JARs from different releases.
The service account needs read access to the ENC exchange set and GDAL data,
and write access to its snapshot cache and GeoServer data directory. Provide
enough disk space for the charts and generated snapshots. Base `.000` files and
their numbered updates must be supplied separately. No scheduled download is needed.

Optional tools are separate from the build dependencies:

| Workflow | Additional dependencies |
| --- | --- |
| Regenerate this ZIP from the repository | Python 3 standard library; run `python3 scripts/package_airgap.py` |
| Maven build instead of the Dockerfile | JDK 17/21, Maven, and cached dependency JARs/POMs/build plugins or an internal repository |
| Prepare a catalogue | Bundled catalogue scripts, Python 3, GDAL Python bindings and local ENC exchange sets |
| Publish a chart group using the installed styles | Bundled publisher, Python 3, GDAL bindings, local chart inventory or snapshot, and REST credentials |
| Run the Java tests | Test sources, JUnit Platform Console Standalone 1.11.4 and native ENC fixtures; full-inventory test additionally needs a prepared catalogue |
| Run Python/image smoke tests | Test scripts and Pillow, with GDAL Python bindings for portrayal generation |

The plugin itself launches `ogr2ogr` as a process. It does not require GeoServer's
GDAL raster extension or GDAL Java/JNI bindings.

## Stage the offline inputs

On a **connected machine**, run `python3 scripts/package_airgap.py` in the full v0.4.0 checkout to create the kit ZIP and its adjacent `.sha256` in `dist/`. From the directory containing that ZIP, package the matching base image for transfer. The example uses the Kartoza default. The target needs a Linux engine compatible with the base image’s CPU architecture.

```bash
set -euo pipefail
export CONTAINER_ENGINE="${CONTAINER_ENGINE:-podman}"
kit=gs-s57-0.4.0-airgap-build.zip
base=docker.io/kartoza/geoserver:2.28.0
sha256sum -c "$kit.sha256"
"$CONTAINER_ENGINE" image inspect "$base" >/dev/null 2>&1 || "$CONTAINER_ENGINE" pull "$base"
kit_media=$(mktemp -d "${TMPDIR:-/tmp}/s57-kit.XXXXXXXX")
cp "$kit" "$kit.sha256" "$kit_media/"
"$CONTAINER_ENGINE" save -o "$kit_media/kartoza-base.tar" "$base"
(cd "$kit_media" && sha256sum kartoza-base.tar "$kit" > SHA256SUMS)
echo "Transfer this directory: $kit_media"
```

On the **disconnected machine**, start in the received directory. Use a writable build directory and either `unzip` or Python 3’s standard-library ZIP extractor. Also transfer an unencrypted S-57 exchange if you want to publish and test a store.

```bash
set -euo pipefail
export CONTAINER_ENGINE="${CONTAINER_ENGINE:-podman}"
sha256sum -c SHA256SUMS
"$CONTAINER_ENGINE" load -i kartoza-base.tar
"$CONTAINER_ENGINE" image inspect docker.io/kartoza/geoserver:2.28.0 --format '{{.Os}}/{{.Architecture}} {{.Id}}'
kit_build=$(mktemp -d "${TMPDIR:-/tmp}/s57-build.XXXXXXXX")
if command -v unzip >/dev/null; then
  unzip -q gs-s57-0.4.0-airgap-build.zip -d "$kit_build"
else
  python3 -m zipfile -e gs-s57-0.4.0-airgap-build.zip "$kit_build"
fi
cd "$kit_build"
sha256sum -c SHA256SUMS
```

## Build

Extract the ZIP and open a terminal in the extracted directory containing
`Dockerfile`, `src` and `portrayal`. The build context is this directory, not its parent.

```bash
docker build --pull=false --network=none --no-cache -t localhost/geoserver-s57:2.28.0 .
```

Or with Podman, which can explicitly refuse all pulls:

```bash
podman build --pull=never --network=none --no-cache --format docker -t localhost/geoserver-s57:2.28.0 .
```

Both commands also work as single lines in PowerShell. Docker's `--pull=false`
does not prevent fetching a missing base, so load the image first. No external
Dockerfile frontend is requested. `--network=none` blocks build-step networking;
the package performs no downloads. A missing dependency causes a build error.

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
Kartoza test instance, set `ENC_CHART_DIR` to an absolute directory containing your chart files and supply `GEOSERVER_ADMIN_PASSWORD` in the host environment. An agent can inherit that secret. For an interactive session, use `read -rsp 'GeoServer password: ' GEOSERVER_ADMIN_PASSWORD` followed by `export GEOSERVER_ADMIN_PASSWORD`.

```bash
set -euo pipefail
: "${ENC_CHART_DIR:?Set the absolute exchange directory}" "${GEOSERVER_ADMIN_PASSWORD:?Set the administrator password}"
export GEOSERVER_ADMIN_PASSWORD
CONTAINER_ENGINE="${CONTAINER_ENGINE:-podman}"
"$CONTAINER_ENGINE" run --pull=never -d --name geoserver-s57 \
  -p 127.0.0.1:18081:8080 \
  -e GEOSERVER_ADMIN_USER=admin \
  -e GEOSERVER_ADMIN_PASSWORD \
  -e INITIAL_MEMORY=512M -e MAXIMUM_MEMORY=2G -e SAMPLE_DATA=false \
  --mount type=volume,src=geoserver-s57-data,dst=/opt/geoserver/data_dir \
  --mount "type=bind,src=$ENC_CHART_DIR,dst=/enc,readonly" \
  localhost/geoserver-s57:2.28.0
```

Those environment variables and data paths are **Kartoza-specific**, not universal
GeoServer settings. Keep any forced extension downloads disabled when offline.
If your base changes its web-application directory during startup, ensure the
installed JAR remains in the active application's `WEB-INF/lib`.

For interactive publication, open `http://localhost:18081/geoserver/`, then choose
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
GDAL drivers can be checked with `"$CONTAINER_ENGINE" exec geoserver-s57 ogrinfo --formats`. For a headless rehearsal, replace the port mapping in the run command with `--network none` and run the check below inside the container.

### Headless check with a real chart

On a fresh Kartoza test instance, an agent can create a single-cell store through REST and read back one feature. This example uses Kartoza’s bundled Python 3 standard library and the credentials set at startup. Set `ENC_CELL` to the **container** path of an actual `.000` under `/enc`. Set `ENC_CLASS` to a populated class listed by `ogrinfo "$ENC_CELL"` inside the container. The example creates the workspace `enc_probe` and stops if that name is already in use. For an already-published installation, query its existing workspace and layer directly.

```bash
: "${ENC_CELL:?Set ENC_CELL to the mounted .000 path, e.g. /enc/US5NY1AI.000}"
export ENC_CELL
export ENC_CLASS="${ENC_CLASS:-SOUNDG}"
"$CONTAINER_ENGINE" exec -i -e ENC_CELL -e ENC_CLASS geoserver-s57 python3 - <<'PY'
import base64, json, os, time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError

root = "http://127.0.0.1:8080/geoserver"
user = os.environ.get("GEOSERVER_ADMIN_USER", "admin")
auth = base64.b64encode((user + ":" + os.environ["GEOSERVER_ADMIN_PASSWORD"]).encode()).decode()
def request(path, body=None):
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": "Basic " + auth, "Content-Type": "application/json"}
    with urlopen(Request(root + path, data=payload, headers=headers), timeout=30) as response:
        return response.read()

for attempt in range(90):
    try:
        request("/rest/about/version.json")
        break
    except URLError as error:
        if getattr(error, "code", None) in (401, 403) or attempt == 89:
            raise
        time.sleep(2)

workspace, layer = "enc_probe", os.environ["ENC_CLASS"]
cell = os.environ["ENC_CELL"]
if not os.path.isfile(cell):
    raise SystemExit("Cell is missing from the container: " + cell)
request("/rest/workspaces", {"workspace": {"name": workspace}})
store = "/rest/workspaces/" + workspace + "/datastores"
params = {"dbtype": "s57", "file": cell, "cache": "/opt/geoserver/data_dir/enc-cache",
          "ogr2ogr": "/usr/bin/ogr2ogr"}
request(store, {"dataStore": {"name": "chart", "connectionParameters": {
    "entry": [{"@key": k, "$": v} for k, v in params.items()]}}})
request(store + "/chart/featuretypes", {"featureType": {"name": layer, "srs": "EPSG:4326"}})
query = urlencode(dict(service="WFS", version="1.0.0", request="GetFeature",
                       typeName=workspace + ":" + layer, maxFeatures=1, outputFormat="application/json"))
features = json.loads(request("/ows?" + query))["features"]
if not features or not features[0]["geometry"]:
    raise SystemExit("No chart geometry returned. Check the cell and object class.")
print("Verified", workspace + ":" + layer, features[0]["id"])
PY
```

## Package contents and scope

- Java production sources and service/Spring/cache resources required by the plugin.
- Pinned portrayal resources, including the S-52 lookup XML and three symbol atlases. The current checkout also carries the inland dictionary CSV inputs.
- The chart viewer, host launcher, catalogue preparation tools, publisher and smoke checks.
- Image recipes, deployment and publishing manuals, build-context exclusions, checksums and license notices.

The plugin recipe compiles its JAR inside the selected base image. The full chart-service recipe installs the viewer at `/enc.html` and uses the bundled publisher to assemble chart groups. Supply the base image and charts separately.

## Checks performed for this kit

| Tested base | GeoServer | GeoTools | Java | GDAL | Scope |
| --- | --- | --- | --- | --- | --- |
| `docker.io/kartoza/geoserver:2.28.0` | 2.28.0 | 34.0 | Temurin 17.0.16 | 3.8.4 | Offline image build; native update, store discovery, WFS and WMS |
| Prepared image derived from official `docker.osgeo.org/geoserver:3.0.2`, with GDAL installed | 3.0.2 | 35.2 | Temurin 21.0.12.1 | 3.8.4 | Offline image build; preserves base settings |
| Vanilla `docker.osgeo.org/geoserver:3.0.2` | 3.0.2 | 35.2 | Temurin 21.0.12.1 | Absent | Java compilation passed; runtime image correctly rejected for missing GDAL |

Tests used **Podman 5.8.2 on Linux x86_64**. Docker/PowerShell command examples
are supplied, but native Windows Docker and other CPU architectures have not
been executed. These specific results are not a guarantee for arbitrary images
or versions. The complete repository retains machine-readable build evidence.

On 2026-11-18, the extracted kit built with Podman on Linux x86_64, with
`--pull=never --network=none --no-cache`, against both Kartoza 2.28.0 and the
project's existing official-GeoServer-3.0.2-based image with GDAL already installed.
The inspected vanilla official 3.0.2 image compiled the Java sources, then was
correctly rejected for missing GDAL. An intentionally wrong GeoServer version
and a base with an older S-57 JAR were also rejected. Other architectures and
vendor images have not been tested. The 0.2.0 Maven build passed 28 Java tests
with no skips; all 15 Python tests also passed. These test tools are not included
in the lean kit and are not needed to build its image.

The Kartoza build validated for release 0.2.0 had JAR entries matching the previously validated plugin's
classes and resources; ZIP timestamps are irrelevant to that comparison. All
base runtime settings were preserved. A fresh lean-image container started
without networking, discovered the S-57 store, applied a real `.001` update,
returned WFS soundings and rendered a nonblank WMS image using a standard style.
No publisher or Python image library was installed for those service checks.

On 2026-11-22, the current checkout’s kit was packaged, checksum-verified, extracted and rebuilt with Podman on Linux x86_64 using the loaded Kartoza base and `--pull=never --network=none --no-cache`. The headless REST example ran on a new network-disabled server and returned `SOUNDG.1` through WFS from NOAA cell `US5NY1AI` with its adjacent update.
