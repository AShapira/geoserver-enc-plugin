# ENC offline build and deployment kit

Release 0.4.0. This directory contains the searchable chart viewer, the `enc` launcher, the catalogue and publishing scripts, the plugin sources and the image build recipes. Supply your chart exchange and a Linux container image for the target architecture separately.

| Task | Instructions |
| --- | --- |
| Build the complete viewer and publisher online, then transfer the finished service | Follow [Transfer a chart service](docs/airgap-deployment.md). Use this extracted directory as the build context and keep the original ZIP for the transfer. |
| Build the complete viewer and publisher **inside** the air gap | Follow the offline build below, then use [Deploy and publish](docs/publishing-guide.md). |
| Add the extension to an existing vendor image | Follow the [plugin image build manual](airgap/README.md). The root `Dockerfile` defaults to Kartoza 2.28.0. |
| Prepare a catalogue from local ZIPs, publish, verify or restore it | Follow [Deploy and publish](docs/publishing-guide.md#prepare-an-exchange-directory). |

## Build the chart service offline

On the connected Linux host, verify the adjacent ZIP checksum with `sha256sum -c gs-s57-0.4.0-airgap-build.zip.sha256`. Extract the ZIP and run the following from the directory containing `enc`. The `service-base` target prepares the official GeoServer 3.0.2 image with its GDAL, Python and font dependencies for the target architecture.

```bash
set -euo pipefail
export CONTAINER_ENGINE="${CONTAINER_ENGINE:-podman}"
export ENC_BASE=localhost/enc-service-base:3.0.2
"$CONTAINER_ENGINE" build -f container/Dockerfile --target service-base -t "$ENC_BASE" .
"$CONTAINER_ENGINE" save -o service-base.tar "$ENC_BASE"
sha256sum service-base.tar > service-base.tar.sha256
```

Transfer the ZIP and its checksum, the image tar and its checksum, and your complete unencrypted S-57 exchange or producer ZIPs. On the disconnected Linux host, start in the directory holding the received files. These commands work with Bash, Python 3.9+, coreutils and a local container engine.

```bash
set -euo pipefail
export CONTAINER_ENGINE="${CONTAINER_ENGINE:-podman}"
export ENC_BASE=localhost/enc-service-base:3.0.2
export ENC_IMAGE=localhost/geoserver-enc:multisource
kit=gs-s57-0.4.0-airgap-build.zip
sha256sum -c "$kit.sha256" service-base.tar.sha256
"$CONTAINER_ENGINE" load -i service-base.tar
"$CONTAINER_ENGINE" image inspect "$ENC_BASE" >/dev/null
kit_dir=$(mktemp -d "$PWD/enc-build.XXXXXXXX")
python3 -m zipfile -e "$kit" "$kit_dir"
cd "$kit_dir"
sha256sum -c SHA256SUMS
pull_option=--pull=false
if [[ "$CONTAINER_ENGINE" == podman ]]; then pull_option=--pull=never; fi
"$CONTAINER_ENGINE" build "$pull_option" --network=none -f container/Dockerfile \
  --build-arg GEOSERVER_IMAGE="$ENC_BASE" --build-arg INSTALL_RUNTIME_PACKAGES=false \
  -t "$ENC_IMAGE" .
```

Continue in this shell with **Set the shell variables** and **Start a new server** in the [publishing guide](docs/publishing-guide.md). For local producer ZIPs, use `python3 enc prepare --archive /path/to/charts.zip --out /path/to/new-exchange`. Use **Publish and verify** to stage the inventory and publish the three chart palettes. Open `/enc.html` on the server's published port, select the source and use **Search objects** to query the visible area by object type and optional name.
