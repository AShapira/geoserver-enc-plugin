# Transfer a complete ENC chart service into an air gap

Prepared by Codex.

If you are reading `START-HERE.md` on received media, begin at [On the disconnected machine](#on-the-disconnected-machine).

Use this procedure for the multi-source GeoServer viewer, named workspaces, shared chart styles, WMS and WMTS. The connected machine builds the full image and prepares the charts. The disconnected machine loads that image and publishes from a local directory. For adding only the Java extension to a vendor’s existing image, use the source-only kit and its included `README.md`.

| Crosses the gap | Why the target needs it |
| --- | --- |
| Full GeoServer **image archive** | Supplies the plugin, GDAL, inland dictionary, Python publisher, fonts, styles compiler and viewer |
| **Operator archive** from the matching checkout | Supplies the host `enc` launcher, its `scripts/providers.py` import, instructions and notices |
| **Exchange archive** | Contains the complete prepared directory, including its manifest, cells, numbered updates and auxiliary files |
| **Transfer record and SHA-256 sums** | Identifies the image tag, exact image ID, OS/architecture and intended workspace, and checks the transferred files before use |

Both machines need Bash, Python 3.9+, a local Linux-container engine, `tar` with gzip, and `sha256sum`. Choose an image built for the target’s CPU architecture. The examples use Podman. Set `CONTAINER_ENGINE=docker` for Docker. The container engine and its host dependencies must already be installed at the disconnected site. Provide GeoServer REST credentials on that site.

## On the connected machine

1. From the repository checkout, follow **Set the shell variables** and **Build the full image online** in the publishing guide at `docs/publishing-guide.md`. Use an image tag that can be loaded on the target without displacing an unrelated local tag.
2. Follow **Prepare an exchange directory** there. A named authority needs internet access at this step. If the producer already supplied an extracted set or ZIPs, use that input instead. Set `ENC_EXCHANGE` to the complete directory and `ENC_WORKSPACE` to the intended workspace.
3. In the same shell, create the transfer directory. Run this from the same checkout that supplied the image. The command uses the actual files on disk, including the host launcher.

```bash
set -euo pipefail
: "${CONTAINER_ENGINE:?}" "${ENC_IMAGE:?}" "${ENC_WORKSPACE:?}" "${ENC_EXCHANGE:?}"
test -f enc && test -f scripts/providers.py && test -d "$ENC_EXCHANGE"
transfer=$(mktemp -d "${TMPDIR:-/tmp}/enc-transfer.XXXXXXXX")
"$CONTAINER_ENGINE" image inspect "$ENC_IMAGE" --format '{{.Id}}' | sed 's/^sha256://' > "$transfer/IMAGE-ID"
"$CONTAINER_ENGINE" image inspect "$ENC_IMAGE" --format '{{.Os}}/{{.Architecture}}' > "$transfer/PLATFORM"
printf '%s\n' "$ENC_IMAGE" > "$transfer/IMAGE-TAG"
printf '%s\n' "$ENC_WORKSPACE" > "$transfer/WORKSPACE"
"$CONTAINER_ENGINE" save --output "$transfer/geoserver.tar" "$ENC_IMAGE"
tar -czf "$transfer/operator.tar.gz" enc scripts/providers.py docs airgap/README.md LICENSE NOTICE.md
tar -czf "$transfer/exchange.tar.gz" -C "$ENC_EXCHANGE" .
cp docs/airgap-deployment.md "$transfer/START-HERE.md"
(
  cd "$transfer"
  sha256sum geoserver.tar operator.tar.gz exchange.tar.gz IMAGE-ID IMAGE-TAG PLATFORM WORKSPACE START-HERE.md > SHA256SUMS
)
echo "Transfer this entire directory: $transfer"
```

Copy that directory, including `SHA256SUMS`, to the disconnected site using your normal transfer medium. The image is the main space requirement. On the target, allow room for the archives, the loaded image, the unpacked exchange and the generated caches. A saved image contains its filesystem layers. Configuration volumes, cached tiles and credentials from a running installation are separate. This procedure recreates the chart publication from its source.

## On the disconnected machine

Start a new Bash shell **in the received directory** containing `SHA256SUMS`. These commands can be run by an agent. They read the transport files from the current directory and write the installation under `$HOME/enc-install`. Set `ENC_INSTALL_ROOT` first to choose another writable filesystem with enough space.

```bash
set -euo pipefail
export CONTAINER_ENGINE="${CONTAINER_ENGINE:-podman}"
transfer=$PWD
sha256sum -c SHA256SUMS
read -r ENC_IMAGE < IMAGE-TAG
read -r ENC_WORKSPACE < WORKSPACE
export ENC_IMAGE ENC_WORKSPACE
cat PLATFORM
"$CONTAINER_ENGINE" load --input "$transfer/geoserver.tar"
actual_id=$("$CONTAINER_ENGINE" image inspect "$ENC_IMAGE" --format '{{.Id}}' | sed 's/^sha256://')
actual_platform=$("$CONTAINER_ENGINE" image inspect "$ENC_IMAGE" --format '{{.Os}}/{{.Architecture}}')
[[ "$actual_id" == "$(cat IMAGE-ID)" && "$actual_platform" == "$(cat PLATFORM)" ]]

mkdir -p "${ENC_INSTALL_ROOT:-$HOME/enc-install}"
install_dir=$(mktemp -d "${ENC_INSTALL_ROOT:-$HOME/enc-install}/deployment.XXXXXXXX")
tar -xzf "$transfer/operator.tar.gz" -C "$install_dir"
export ENC_EXCHANGE="$install_dir/exchange"
mkdir "$ENC_EXCHANGE"
tar -xzf "$transfer/exchange.tar.gz" -C "$ENC_EXCHANGE"
cd "$install_dir"
python3 enc deploy --help >/dev/null
echo "Continue from $install_dir using docs/publishing-guide.md"
```

A checksum or image identity mismatch stops the shell before publication. Retrieve the matching transfer files and repeat the import. Compare the recorded platform with the target engine’s supported architecture if the container reports `exec format error`.

**Finish in the same shell** using the extracted publishing guide at `$install_dir/docs/publishing-guide.md`.

1. Run **Set the shell variables**. It preserves the imported image, exchange and workspace. Set `ENC_CONTAINER` and `ENC_PORT` for the intended target. Supply credentials through the environment if needed.
2. For a fresh installation run **Start a new server**, then **Check the server**. For an existing compatible service, run only **Check the server** and verify that its running image is the one you intend to publish with. Image loading alone does not switch a running container.
3. Go directly to **Publish and verify**. The inputs are already extracted. Keep its receipt. A passing result has the expected workspace and generation, a positive reconciled cell count, and three palette entries with a repeated WMTS `HIT`.

To check the running image in step 2, run this in the target shell after selecting or starting the server. A mismatch means that container still uses a different build. Select the intended container or use the site’s normal image-upgrade procedure before publishing.

```bash
running_id=$("$CONTAINER_ENGINE" inspect "$ENC_CONTAINER" --format '{{.Image}}' | sed 's/^sha256://')
[[ "$running_id" == "$(cat "$transfer/IMAGE-ID")" ]]
```

The target uses the loaded image with `--pull=never`. The staging helper runs with `--network none`. The publisher and protocol checks use GeoServer’s in-container loopback address. A disconnected machine can still serve a browser through the configured host port. For a fully network-disabled rehearsal, use the headless option in **Start a new server** and check the results with `exec`.

## Send a chart update

For another edition on the same runtime, prepare the new exchange on the connected host. Transfer a new archive and checksum. Keep each prior generation and its receipt until you have verified the replacement.

**Connected shell**, with `ENC_EXCHANGE` set to the new complete exchange:

```bash
set -euo pipefail
update_dir=$(mktemp -d "${TMPDIR:-/tmp}/enc-update.XXXXXXXX")
tar -czf "$update_dir/exchange.tar.gz" -C "$ENC_EXCHANGE" .
(cd "$update_dir" && sha256sum exchange.tar.gz > SHA256SUMS)
echo "Transfer both files from $update_dir"
```

**Disconnected shell**, starting in the previously extracted installation that contains `enc`. Set `ENC_UPDATE_MEDIA` to the received update directory and keep the same container and workspace settings as the previous deployment:

```bash
set -euo pipefail
: "${ENC_UPDATE_MEDIA:?Set the path to the received update directory}"
(cd "$ENC_UPDATE_MEDIA" && sha256sum -c SHA256SUMS)
export ENC_EXCHANGE
ENC_EXCHANGE=$(mktemp -d "$PWD/exchange-update.XXXXXXXX")
tar -xzf "$ENC_UPDATE_MEDIA/exchange.tar.gz" -C "$ENC_EXCHANGE"
```

Run **Publish and verify** again, with the previous display options. To restore the previous edition, point `ENC_EXCHANGE` back to the saved directory and use the same procedure. Transfer a new full image and matching operator files when the runtime itself changes.

## Rehearsal

On 2026-11-22, a connected Linux x86_64 Podman instance downloaded and published Belgium’s 118-cell exchange. A second, initially empty Podman image store on the same workstation loaded the saved image. With the target server’s network disabled, the transferred files produced the same generation ID, three distinct WMS palettes and WMTS cache hits for all three palettes. A chart-only update to a single Zeebrugge cell passed the same checks. Restoring the retained exchange recovered the original 118-cell generation. A damaged transfer failed its checksum before deployment. Native Docker and transfer between physical machines were outside this rehearsal.
