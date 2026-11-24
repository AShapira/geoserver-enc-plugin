# Deploy S-57 charts to GeoServer

Prepared by Codex.

| Starting point | What to do |
| --- | --- |
| You have a running multi-source GeoServer | Set the shell variables, check the server, then prepare and deploy an exchange. |
| You are installing online | Follow the steps below in order, including the image build and first start. |
| The target has no internet access | Start with the [two-machine air-gap procedure](airgap-deployment.md). It supplies the image, charts, host command and manuals. Resume here after import. |
| You need only the extension JAR in an existing server image | Use the [plugin build manual](../airgap/README.md) or the [Kartoza 2.28.0 manual](kartoza-2.28.0.md). |
| You maintain the original NOAA XML/archive installation | Use the [NOAA maintenance procedure](noaa-catalogue-maintenance.md). A NOAA workspace created by `enc deploy` follows this guide. |

## Set the shell variables

Run the blocks in **one Bash shell** on the Linux container-engine host, from the checkout containing `enc` or the extracted operator bundle. The host needs Python 3.9+ and a local Podman or Docker engine that can mount the exchange directory. GDAL, Java and Pillow come with the full server image. Use a writable working directory for deployment receipts.

```bash
set -euo pipefail
export CONTAINER_ENGINE="${CONTAINER_ENGINE:-podman}"
export ENC_CONTAINER="${ENC_CONTAINER:-geoserver-enc}"
export ENC_IMAGE="${ENC_IMAGE:-localhost/geoserver-enc:multisource}"
export ENC_PORT="${ENC_PORT:-18080}"
export ENC_WORKSPACE="${ENC_WORKSPACE:-be_coast}"
export ENC_EXCHANGE="${ENC_EXCHANGE:-$PWD/exchanges/belgium-1}"
python3 enc deploy --help >/dev/null
```

`ENC_CONTAINER` selects the GeoServer process. `ENC_WORKSPACE` selects the collection inside it. Start its name with a letter and use ASCII letters, digits and underscores. Use a different workspace for each collection you want to serve side by side. For an existing server, the publisher uses that container’s actual image and writable cache mount.

With default credentials the loopback demo uses `admin` and `geoserver`. To configure a fresh server or authenticate to an existing account, supply `GEOSERVER_USER` and `GEOSERVER_PASSWORD` through the environment. An unattended agent can inherit them from its secret store. In an interactive shell you can prompt for the password:

```bash
export GEOSERVER_USER=admin
read -rsp 'GeoServer REST password: ' GEOSERVER_PASSWORD
echo
export GEOSERVER_PASSWORD
```

## Build the full image online

Skip this step for a running compatible server or a verified image loaded from the transfer bundle. On a connected host, run the build from the checkout root or the extracted kit containing `enc`. The base image and OS packages must be available. The image architecture must match the target.

```bash
build_options=()
if [[ "$CONTAINER_ENGINE" == podman ]]; then build_options=(--format docker); fi
"$CONTAINER_ENGINE" build "${build_options[@]}" -f container/Dockerfile -t "$ENC_IMAGE" .
```

## Start a new server

For an existing installation, go directly to [Check the server](#check-the-server). For a fresh installation, choose a free container name, its two new volume names, and a free loopback port. The engine creates named volumes for GeoServer configuration and chart data. Allow space on the host for the exchange and in the engine’s storage for the image, staged sources, GeoPackages, edge databases and tiles. A refresh needs space alongside the previous generation.

```bash
enc_access=(-p "127.0.0.1:$ENC_PORT:8080")
```

On a fresh configuration volume, the start command passes any supplied publisher credentials to the official image as its initial administrator settings. For a service test with the container network disabled, set `enc_access=(--network none)` instead. The checks below run inside the server and work in either mode. Browser access uses the published port.

```bash
enc_admin=()
if [[ -n ${GEOSERVER_PASSWORD:-} ]]; then
  export GEOSERVER_ADMIN_USER="${GEOSERVER_USER:-admin}"
  export GEOSERVER_ADMIN_PASSWORD="$GEOSERVER_PASSWORD"
  enc_admin=(-e GEOSERVER_ADMIN_USER -e GEOSERVER_ADMIN_PASSWORD)
fi
"$CONTAINER_ENGINE" run --pull=never -d --name "$ENC_CONTAINER" "${enc_admin[@]}" \
  --restart unless-stopped --memory 6g "${enc_access[@]}" \
  -v "${ENC_CONTAINER}-config:/opt/geoserver_data" \
  -v "${ENC_CONTAINER}-cache:/opt/enc-cache" "$ENC_IMAGE"
```

## Check the server

These checks also apply when adding charts to an existing instance. They confirm that the target has the publisher and inland dictionary, exposes a writable cache mount to the staging helper, and accepts requests on its internal GeoServer port.

```bash
"$CONTAINER_ENGINE" inspect --format '{{json .Mounts}}' "$ENC_CONTAINER" | python3 -c '
import json, sys
mounts = {m["Destination"]: m for m in json.load(sys.stdin)}
if not mounts.get("/opt/enc-cache", {}).get("RW"):
    sys.exit("The target needs a writable volume or bind mount at /opt/enc-cache")
'
"$CONTAINER_ENGINE" exec "$ENC_CONTAINER" sh -ec '
  test -r /opt/enc/scripts/deployment.py
  test -x /opt/enc/scripts/ogr_inland.py
  test -r /opt/enc/s57/s57objectclasses.csv
'
enc_root=http://127.0.0.1:8080/geoserver
enc_capabilities="$enc_root/ows?service=WMS&request=GetCapabilities&version=1.3.0"
for attempt in {1..90}; do
  if "$CONTAINER_ENGINE" exec "$ENC_CONTAINER" curl -fsS --max-time 5 "$enc_capabilities" >/dev/null 2>&1; then break; fi
  sleep 2
done
"$CONTAINER_ENGINE" exec "$ENC_CONTAINER" curl -fsS --max-time 10 "$enc_capabilities" >/dev/null
```

If readiness fails, inspect `"$CONTAINER_ENGINE" logs --tail 80 "$ENC_CONTAINER"` before starting an import. If a publisher or dictionary file is missing, select the container created from the full image.

## Prepare an exchange directory

Choose **one** input. A named provider’s job ends when it produces the directory. Deployment then follows the same steps for every source.

**Named authority, connected host.** This example downloads Belgium. Substitute a provider from the table below and set `ENC_EXCHANGE` to a new output directory for each preparation.

```bash
python3 enc prepare --provider be_coast --out "$ENC_EXCHANGE"
```

**Producer ZIPs, either environment.** Use the ZIPs that together contain the complete set. Set the paths and workspace for your collection first.

```bash
export ENC_WORKSPACE=local_charts
export ENC_EXCHANGE="$PWD/exchanges/local-1"
python3 enc prepare --archive /path/to/region-a.zip /path/to/region-b.zip --out "$ENC_EXCHANGE"
```

**Already extracted, either environment.** Set `ENC_EXCHANGE` to the outer directory. This is also the entry point for charts delivered through the air gap. Keep each base and its numbered updates in the producer’s directory structure, with any auxiliary files. A prepared bundle includes `exchange.json`. A producer’s own extracted directory can be deployed without it.

```bash
# Example for an operator-supplied ENC_ROOT. Substitute the actual host path.
export ENC_WORKSPACE=local_charts
export ENC_EXCHANGE=/path/to/ENC_ROOT
```

## Publish and verify

The following block is the **unattended deployment entry point** once the target, credentials and input directory are set. It records the staged generation, checks that GeoServer advertises that same generation and cell count, and requests chart images. A successful `ENC_GENERATION=…` line on its own means staging finished. Publication and rendering still have to succeed.

For a named provider, leave `enc_display` empty to use its title and bookmark. For your own exchange, you can set it to an array such as `enc_display=(--title "Ohio River" --view -80.013 40.438 17)` if that point is covered. Coordinates are longitude, latitude, then an integer zoom from 2 to 20. Detailed harbour charts often need zoom 17–19.

```bash
enc_display=()
```

```bash
set -euo pipefail
enc_root=http://127.0.0.1:8080/geoserver
mkdir -p receipts
enc_receipt=$(mktemp -d "$PWD/receipts/${ENC_WORKSPACE}.XXXXXXXX")
"$CONTAINER_ENGINE" inspect --format '{{.Image}}' "$ENC_CONTAINER" > "$enc_receipt/image-id.txt"
printf '%s\n' "$ENC_EXCHANGE" > "$enc_receipt/exchange-path.txt"
printf '%s\n' "${enc_display[@]}" > "$enc_receipt/display-options.txt"
python3 enc deploy "$ENC_EXCHANGE" --workspace "$ENC_WORKSPACE" "${enc_display[@]}" \
  2>&1 | tee "$enc_receipt/deploy.log"
enc_generation=$(sed -n 's/^ENC_GENERATION=//p' "$enc_receipt/deploy.log")
[[ "$enc_generation" =~ ^[0-9a-f]{64}$ ]]
enc_dir="/opt/enc-cache/catalogues/$ENC_WORKSPACE/$enc_generation"
"$CONTAINER_ENGINE" cp "$ENC_CONTAINER:$enc_dir/catalogue-report.json" "$enc_receipt/inventory.json"
"$CONTAINER_ENGINE" exec "$ENC_CONTAINER" curl -fsS "$enc_root/www/enc-sources.json" > "$enc_receipt/registry.json"
python3 - "$enc_receipt" "$ENC_WORKSPACE" "$enc_generation" <<'PY'
import json, sys
from pathlib import Path
receipt, workspace, generation = sys.argv[1:]
data = Path(receipt)
entry = json.loads((data / "registry.json").read_text())[workspace]
inventory = json.loads((data / "inventory.json").read_text())
if (entry["generation"] != generation or entry["cells"] != inventory["indexed_cells"]
        or entry["cells"] < 1 or inventory["failures"]):
    sys.exit("Published generation or cell count differs from the staged inventory")
print(workspace, entry["cells"], "indexed cells", generation)
PY
enc_check_dir="/tmp/$(basename "$enc_receipt")"
"$CONTAINER_ENGINE" exec "$ENC_CONTAINER" python3 /opt/enc/scripts/check_sources.py \
  --url "$enc_root" --workspace "$ENC_WORKSPACE" --out "$enc_check_dir"
"$CONTAINER_ENGINE" cp "$ENC_CONTAINER:$enc_check_dir/results.json" "$enc_receipt/results.json"
echo "Verified deployment. Receipt: $enc_receipt"
```

Success means the block exits zero and the receipt includes `results.json` for day, dusk and night. The check renders a nonblank WMS image and WMTS tile for each palette, checks that the palettes differ and confirms a repeated WMTS tile is a cache `HIT`. An agent can return the workspace, generation, cell count, viewer URL and receipt path. Retain the source exchange referenced by the receipt for rollback. If the stage needs fewer import processes, pass `--workers 2` to `enc deploy` (default 4, range 1–16).

At the default host port, open the [viewer](http://127.0.0.1:18080/enc.html), choose **Source**, then try **Palette** and **Service**. At zoom 10 or closer, **Search objects** finds chart features in the current map area by type and optional partial name. Other GIS clients can discover `WORKSPACE:chart_day`, `chart_dusk` and `chart_night` through [WMS](http://127.0.0.1:18080/geoserver/wms?SERVICE=WMS&REQUEST=GetCapabilities) or [WMTS](http://127.0.0.1:18080/geoserver/gwc/service/wmts?SERVICE=WMTS&REQUEST=GetCapabilities). Use the chosen host port if it differs from 18080.

Each workspace has its own inventory, cache and chart groups. The plugin installs the [global style library](shared-styles.md) at startup. Each publication selects the installed styles for its chart classes. Lowercase inland classes use an `i_` prefix to preserve distinct classes in SQLite. The inventory records edition, applied updates, scale and classes per cell. Under `$enc_dir`, inspect `cache/warm-report.json` for conversions, `edge-report.log` for native edges, and `portrayal-day/publication.json` for plotted classes and portrayal gaps.

## Choose a provider

A provider’s job ends when it produces an exchange directory. The directory can move between machines or change names. Preserve the entire tree, including `exchange.json`, update files and supporting documents. For a local directory the manifest is optional. Named preparations write package URLs, download time and SHA-256 hashes there. The counts below describe the tested snapshot of November 19, 2026. The [deployment record](enc-validation.json) includes package hashes, applied updates, portrayal gaps, and live rendering checks.

| Provider | Indexed cells | What opens and where the data comes from |
| --- | ---: | --- |
| `noaa` | 7,114 | New York Harbor. Maritime ENCs for US waters and territories. The retained NOAA inventory is dated November 14. [NOAA downloads](https://charts.noaa.gov/ENCs/ENCs.shtml) |
| `be_coast` | 118 | Zeebrugge. The Belgian country export includes coastal cells along the North Sea from the French to the Dutch border and inland waterways. [Flemish Hydrography catalogue](https://www.agentschapmdk.be/nl/bijlage/257c3205-5ffe-423e-8726-0dc7ebeac4bf/catalogus-juni-2026.pdf) · [EuRIS](https://www.eurisportal.eu/enc) |
| `ro_danube` | 177 | The buoyed channel at Sulina. The country export includes the Danube delta, river mouths, canals and cross-border holdings. Offshore Romanian maritime charts are a separate product. [AFDJ Inland ENC](https://www.afdj.ro/en/content/inland-enc) · [Danube Commission](https://www.danubecommission.org/dc/en/danube-navigation/electronic-navigational-charts-enc-for-the-danube-river/) |
| `nl_rws` | 190 | Vlissingen. Rijkswaterstaat’s inland network, Zeeland and Wadden Sea production packages. [Dutch open-data catalogue](https://data.overheid.nl/dataset/3482b76e-d53f-42c4-98a2-7500f708b190) |
| `de_wsv` | 479 | Berlin-Spandau shipping canal. Germany’s 42 federal waterway packages include the Rhine, Elbe and Danube. [WSV / ELWIS](https://www.elwis.de/DE/dynamisch/IENC/) · [Reuse terms](https://www.elwis.de/DE/dynamisch/enc-dateien/GeoNutzV/index.html) |
| `usace` | 109 | The river confluence at Pittsburgh. The US Army Corps of Engineers’ national inland river collection. [USACE S-57 catalogue](https://ienccloud.us/ienc_s57.html) |

The viewer displays producer attribution. Belgium and Romania use the national exports distributed through EuRIS and include its service credit. Preserve the producer’s terms when redistributing a set. Public download access alone does not establish uniform licensing across all producers. [EuRIS service terms](https://www.eurisportal.eu/content/about/api)

## Refresh or restore a source

**Refresh.** Retain the previous exchange and receipt. On a connected machine, prepare the next edition into a fresh directory. For an air-gapped target, transfer and verify the new exchange as described in the [handoff procedure](airgap-deployment.md#send-a-chart-update). Set `ENC_EXCHANGE` to the new directory, keep `ENC_WORKSPACE` the same and rerun **Publish and verify**. Deploying the same directory again reuses its staged generation.

**Restore only if needed.** Set `ENC_EXCHANGE` back to the previous directory, restore its title and view options, then rerun **Publish and verify**. Compare the resulting generation with the previous receipt. If you only have the retained generation, copy its exchange from the cache to a fresh host directory first:

```bash
# Supply the 64-character generation from the last good receipt.
: "${PREVIOUS_GENERATION:?Set PREVIOUS_GENERATION from the last good receipt}"
[[ "$PREVIOUS_GENERATION" =~ ^[0-9a-f]{64}$ ]]
enc_restore=$(mktemp -d "$PWD/restore.XXXXXXXX")
"$CONTAINER_ENGINE" cp "$ENC_CONTAINER:/opt/enc-cache/catalogues/$ENC_WORKSPACE/$PREVIOUS_GENERATION/exchange" "$enc_restore/exchange"
export ENC_EXCHANGE="$enc_restore/exchange"
```

Staging errors occur before publication. The chart groups track the selected generation. Older individual layer registrations can remain after holdings shrink. A REST failure can leave a partially updated workspace because the store, layers, groups and tile caches change through separate requests. Retry the full deployment or restore the last verified exchange. If clients need uninterrupted access, or the replacement covers a different geographic area, publish and verify a new workspace before changing client group names. GeoWebCache can retain explicit tile bounds from the previous publication. For an expanded collection, also check a covered location in the new area. Keep the configuration and cache volumes together when recreating the server. The original NOAA installation keeps its inventory on a separate volume and has its own [restore procedure](noaa-catalogue-maintenance.md#d-roll-back-if-validation-fails).

## Troubleshooting

- **WMS passes but WMTS returns HTTP 400.** A WMTS response with `TileOutOfRange` inside the new chart coverage can mean that GeoWebCache still has the old tile extent. The registry and WMS can already show the new generation. Publish the replacement under a new `ENC_WORKSPACE` and run **Publish and verify** at the affected location. If you updated the original workspace, restore and verify its previous exchange before handing that workspace back to clients. To preserve its name in an installation with custom tile limits, review the grid subset extents for `chart_day`, `chart_dusk` and `chart_night` in both EPSG:4326 and EPSG:900913. The extent in each grid’s own CRS must include the new coverage. Tile truncation alone does not change those limits.
- **Prepare says the directory exists.** Select a new output path to download a fresh snapshot. To reuse an already prepared directory, proceed directly to deployment.
- **REST returns 401 or 403.** Check that the provided account can publish workspaces, global styles and GeoWebCache groups. Pass its credentials through the environment on the host running `enc deploy`.
- **Staging or disk-space failure.** Check free space both on the exchange filesystem and in container storage. Inspect the receipt log and the reported path under `/opt/enc-cache/catalogues/WORKSPACE/`. An index failure may leave `failed-GENERATION.json` there. Preserve the serving generation while correcting the input.
- **Blank overview.** Select the source again to return to its opening view, then zoom in. Detailed Inland ENCs can cover a narrow channel and have no overview band. The extent includes the whole collection, sometimes including cross-border cells.
- **Missing update or conflicting copies.** Keep `.001`, `.002` and later files next to their matching `.000`. Preserve the producer’s directory structure and use a complete reissued base or a continuous chain. The importer rejects divergent duplicate copies. NOAA also reconciles against the active product catalogue.
- **Unexpected input format.** Supply unencrypted S-57 base cells or a ZIP containing them. Encrypted S-63 products, S-101 datasets and rendered map tiles require other readers.
- **Source data issues.** One Romanian export cell, `3R7PAM02`, has a truncated edition 1/update 5. Preparation retains its original bytes and records the hash-verified replacement edition 1/update 7 from Danube FIS. Another cell, `2P7D0942`, omits the coverage category. It is inventoried, but contributes no charted area. [Danube FIS published archive](https://www.danubeportal.com/application/cache/uploads/charts/electronic/RO/10/1726821665.zip)
- **Incomplete native linework.** Two German Main cells (`1W7MA230` and `1W7MA240`) have three edges without both endpoint nodes. Five feature-to-edge references are omitted from native line rendering. The affected sidecar databases record the class, feature ID and edge ID in `omitted_links`.
- **Nonnumeric source depths.** In the Dutch cell `1R7EMS02`, GDAL 3.8 reads the literal `UNKNOWN` in an obstruction depth as zero. Interpret that value as unknown.
- **Missing chart details.** This experimental renderer implements part of the S-52 and Inland ENC portrayal rules. Inspect the publication report for omissions. Use official navigation products for navigation. [Portrayal coverage](portrayal.md)
