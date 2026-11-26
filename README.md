# GeoServer S-57 ENC plugin

A read-only GeoServer S-57 plugin backed by GDAL's S57 reader. Release **0.6.0** adds a standalone catalog manager for downloading ENC exchange sets, preparing catalogs offline, and exporting them for deployment. The plugin installs a shared ENC style library before any charts are loaded and includes an [air-gap build and deployment kit](docs/airgap-deployment.md) maintained on `main`. Tested Java targets are **GeoServer 2.28.0 / GeoTools 34.0** and **GeoServer 3.0.2 / GeoTools 35.2**; other versions require rebuilding and validation. Each catalogue store serves a complete S-57 exchange set through WMS and GeoWebCache WMTS. It indexes actual chart coverage, selects cells by scale and clips overlapping coverage. Adjacent updates are applied to immutable, indexed GeoPackage snapshots. Single `.000` stores remain supported.

The supplied portrayal compiler uses pinned OpenCPN S-52 colours, raster symbols, lookup tables, and HPGL patterns/lines. It supplies depth bands, selected safety contours, compound sounding glyphs, light sectors/characteristics, topmarks, formatted labels, scale filtering, and day/dusk/night presets. Versioned [native edge metadata](docs/edge-metadata.md) handles conditional shared-edge priorities, masks, spatial-quality segments and precomputed lookup selection. **Portrayal is experimental and incomplete; this is not an ECDIS implementation or a claim of S-52 conformance.** See [portrayal coverage](docs/portrayal.md) and the [latest OpenCPN comparison and CPU/RAM/disk measurements](docs/portrayal-2026-11-17.md).

The plugin includes an **ENC viewer and search demo** at `<geoserver-base>/enc/viewer/index.html`. Publish a feature type from any S-57 datastore, then open **Layers** to display it or **Search objects** to find features in the current map area. Named ENC chart groups appear in **Chart**. The viewer uses the user's GeoServer permissions and works offline.

## Prepare catalogs in a local browser

From this checkout on Linux, run the following commands. The first prepares the Podman operator image and plugin assets while connected. Docker users can set `CONTAINER_ENGINE=docker`. Preparation runs independently of a GeoServer process.

```bash
container/runtime.sh
./enc manager --data-dir "$HOME/enc-library"
```

Open the loopback URL printed by the manager (default port 18765). Choose one of the six built-in providers or use **Add provider** and enter a direct HTTP(S) ZIP URL, a local ZIP path, or a local S-57 exchange folder. The local path is on the machine running the manager. You can edit a custom provider’s display name or location later.

1. **Download exchange** or **Import exchange** saves a dated copy with its source and checksum. Keep base cells and numbered updates together. An existing exchange manifest in the source root retains its inventory rules.
2. **Prepare catalog** on a saved exchange builds its SQLite index, GeoPackages, and edge data offline. Follow the job log or close the browser and return later. Failed jobs can be retried. Each refresh saves a new source snapshot.
3. **Export for transfer** writes a verified ZIP under the data directory’s `exports/` folder. Copy it to a matching installation, compare its SHA-256 to the value shown in the manager, then run `./enc deploy --prepared /path/to/package.zip`. The package carries its destination workspace.

Keep the manager data directory between runs. Allow space for the source snapshot, staged exchange, converted cache, and export. The [air-gap deployment guide](docs/airgap-deployment.md) covers disconnected installations.

## Deploy an ENC collection

| Task | Manual |
| --- | --- |
| Find national ENC publishers, chart coverage, downloads and reuse terms | [National charting agencies and their electronic navigational charts](docs/enc-charting-agencies.md) |
| Install the full server online, add a provider or local exchange, verify the charts, or roll back a workspace | [Publish an ENC collection](docs/publishing-guide.md) |
| Transport the full chart service and data to a disconnected site | [Air-gapped deployment](docs/airgap-deployment.md) |
| Install a versioned plugin ZIP on an existing GeoServer | [Standalone install manual](airgap/README.md) |
| Build S-57 into GeoServer Cloud 3.0.0 and 3.0.2 services | [Cloud integration and checks](cloud/README.md) |
| Maintain the original NOAA XML/archive demo | [NOAA catalogue maintenance](docs/noaa-catalogue-maintenance.md) |

**Quick start for an already running multi-source server.** In a Bash shell on its host, run from the matching checkout. A named provider prepares the exchange directory. The same deployment command accepts your own extracted S-57 exchange. All workspaces share portrayal styles and graphics.

```bash
set -euo pipefail
python3 enc prepare --provider be_coast --out exchanges/belgium
python3 enc deploy exchanges/belgium --workspace be_coast
container/operator.sh python3 /opt/enc/scripts/check_sources.py \
  --url http://127.0.0.1:8080/geoserver --workspace be_coast
```

Open the [chart viewer](http://127.0.0.1:18080/geoserver/enc/viewer/index.html) and select a published chart or individual ENC layer. For an unattended deployment with generation checks and a saved WMS/WMTS receipt, follow [Publish and verify](docs/publishing-guide.md#publish-and-verify).

## Try the NOAA demo

For a fresh NOAA demo, run from this directory with Podman and network access. This launcher uses the original three-volume NOAA layout. To add NOAA to an existing two-volume chart server, use `enc prepare --provider noaa` and the generic publishing guide.

```bash
container/demo.sh
```

Open **[the interactive chart](http://127.0.0.1:18080/geoserver/enc/viewer/index.html)**. Choose a published chart and palette, or open **Layers** to display individual ENC layers. Pan or zoom within the chart coverage.

The launcher starts the stock **`docker.osgeo.org/geoserver:3.0.2-gdal`** image with the locally built extension ZIP mounted in its community plugin directory. A separate operator container handles publication, prewarming and tile seeding. The first run downloads NOAA's full exchange archive and prepares every active cell. The validated snapshot contains **7,114 active cells, 6,965,828 source features and no failed imports**, from the catalogue valid 2026-11-14. A single current metadata generation uses about **15 GiB** for sources, converted data, edge sidecars and GeoServer state, plus container images; allow at least 25 GiB free. Retained older metadata generations consume additional space. Downloads, imports and first tile renders take time.

The container runs detached as `geoserver-enc`, publishes IPv4 loopback port 18080, has a health check and uses `unless-stopped`. This port was verified from both WSL and Windows localhost. Windows/WSL forwarding still depends on the local WSL configuration. No firewall changes are made. To rebuild after source changes, retaining the catalogue and caches:

```bash
container/demo.sh --recreate
podman logs --tail 50 geoserver-enc
```

If an immediate restart reports pasta `Address already in use`, let the old port forwarder exit, then run `podman start geoserver-enc` again. This transient Podman behavior occurred once during validation; the volumes and publication were retained.

`CONTAINER_ENGINE=docker container/demo.sh` selects Docker (the executed validation used Podman). `ENC_PORT=18081` selects another local port when creating a container. An existing container keeps its previous port until `--recreate`.

Three dedicated named volumes retain data: `geoserver-enc-catalogue` (read-only in the server), `geoserver-enc-cache`, and `geoserver-enc-data`. The script preserves them when recreating the server. It reuses an existing inventory; **it does not automatically refresh NOAA data**. The demo retains the official image's initial `admin` / `geoserver` credentials and is intended for local access.

Endpoints:

- Viewer: <http://127.0.0.1:18080/geoserver/enc/viewer/index.html>
- Admin: <http://127.0.0.1:18080/geoserver/>
- WMS: <http://127.0.0.1:18080/geoserver/wms>
- WMTS capabilities: <http://127.0.0.1:18080/geoserver/gwc/service/wmts?SERVICE=WMTS&REQUEST=GetCapabilities>
- Groups: `noaa:chart_day`, `noaa:chart_dusk`, `noaa:chart_night`.
- WMTS grid sets: `EPSG:4326` and `EPSG:900913` (Web Mercator).

See the [step-by-step NOAA setup and update guide](docs/noaa-catalogue-maintenance.md),
[full-catalogue validation](docs/catalogue-validation.md), [standalone installation](airgap/README.md) and [design decisions](docs/decisions.md).

### Optional single-cell development demo

Linux x86_64, Python 3.12+ and network access are needed for the bootstrap. Dependencies stay inside `.runtime/`; no containers or system package changes are needed. It downloads roughly a few hundred MB. The pinned packages include Java 21, Maven, GDAL 3.11.5, Python and Pillow.

```bash
python3 scripts/bootstrap.py
scripts/build.sh
scripts/serve.sh
```

Leave the last command running. In a second shell, from this directory:

```bash
export GEOSERVER_PASSWORD=geoserver  # fresh, loopback-only demo distribution
scripts/demo.sh
```

This downloads NOAA **US5NY1BH**, publishes `noaa:chart_day`, and runs the protocol smoke tests. Results appear in `evidence/`, including `wms-overview.png`, `wms-detail.png`, `wmts-tile.png`, and `smoke.json`. The script prints the WMS image URL. It refuses to overwrite an existing workspace unless you explicitly pass `--update`:

```bash
scripts/demo.sh --update
```

Endpoints while the demo is running:

- Admin: <http://127.0.0.1:18080/geoserver/>
- WMS: <http://127.0.0.1:18080/geoserver/wms>
- WMTS capabilities: <http://127.0.0.1:18080/geoserver/gwc/service/wmts?SERVICE=WMTS&REQUEST=GetCapabilities>
- Layer/group: `noaa:chart_day`; WMTS grid sets `EPSG:4326` and `EPSG:900913` (Web Mercator).

The bootstrap preserves an existing demo data directory. Stop the foreground server with Ctrl-C (or `python3 scripts/stop-demo.py`) before replacing the plugin JAR. It binds only to `127.0.0.1`; this demo retains GeoServer's initial credentials and is not a public deployment configuration.

## Install in an existing GeoServer

Build both plugin releases with `container/build-plugins.sh`. Install the matching ZIP using the [official image procedure](airgap/README.md) or the [Kartoza 2.28.0 procedure](docs/kartoza-2.28.0.md). For disconnected sites, [export the stock image, plugin and operator kit](docs/airgap-deployment.md). For GeoServer Cloud, use the [release-specific service image build](cloud/README.md).

1. Use a tested target with Java 17 or 21, and GDAL 3.2+ with S57, GPKG and SQLite drivers (tested with 3.8.4 in containers and 3.11.5 in development). Ensure GDAL's data dictionaries and PROJ data are available to the server process.
2. Build with `mvn package` for GeoServer 3.0.2, or `mvn -Pgeoserver-2.28 package` for 2.28.0. Stop GeoServer, remove an older S-57 plugin JAR if upgrading, copy **only** `target/gs-s57-0.6.0.jar` into `WEB-INF/lib`, then restart. The tested binaries already contain `gt-geopkg` and its dependencies; do not replace GeoTools JARs. If your custom distribution omits them, install its matching GeoPackage support first. The first startup installs the [shared ENC style library](docs/shared-styles.md), including all three palettes, before any chart store exists.
3. Add a store of type **S-57 ENC (GDAL)**, supplying:

| Parameter | Value |
| --- | --- |
| `dbtype` | `s57` |
| `catalogue` | Absolute path to a prepared `catalogue.sqlite`; use this for an indexed S-57 exchange set |
| `file` | Alternative absolute path to one `.000` file; specify exactly one of `file` and `catalogue` |
| `cache` | Absolute writable cache directory, outside the source exchange set |
| `ogr2ogr` | Absolute path to GDAL's `ogr2ogr` executable |
| `timeout` | Import timeout in seconds; default 300 |
| `namespace` | Optional feature namespace URI |
| `cellPoolSize` | Catalogue JDBC store pool target; default 16, demo 32; active readers remain leased |
| `shallowDepth`, `safetyDepth`, `deepDepth` | Store thresholds in metres for all three palettes. Defaults are 2, 5, and 10 respectively. |

4. Publish object classes in the GeoServer UI, or use `scripts/publish.py` to generate and install the complete ordered chart group. The publisher requires GDAL Python bindings, REST administrator credentials, and access to the chart inventory or snapshot. It manages one catalogue or single-cell store per workspace. To prepare a catalogue, download `ENCProdCat.xml` and `All_ENCs.zip` from NOAA, then run:

```bash
python scripts/catalogue.py --catalogue /path/ENCProdCat.xml \
  --archive /path/All_ENCs.zip --out /path/noaa-catalogue
python scripts/publish.py --catalogue /path/noaa-catalogue/catalogue.sqlite \
  --url http://127.0.0.1:18080/geoserver --workspace noaa \
  --data-dir /path/geoserver-data --cache /path/enc-cache --ogr2ogr /usr/bin/ogr2ogr
```

For a single cell instead:

```bash
source scripts/env.sh  # only when using the supplied local runtime
export GEOSERVER_PASSWORD='your-server-password'
python scripts/publish.py /absolute/path/US5NY1BH.000 \
  --url http://127.0.0.1:18080/geoserver --workspace noaa \
  --data-dir /absolute/path/to/geoserver/data_dir \
  --cache /absolute/path/to/cache --ogr2ogr /absolute/path/to/ogr2ogr
```

Set `--palette dusk` or `--palette night`, `--styles portrayal/generated-night`, and `--update` to add another preset to an existing plugin-owned workspace. The groups `chart_day`, `chart_dusk`, and `chart_night` have separate tile caches. `--shallow 2 --safety 5 --deep 10` sets the store’s metre thresholds for every palette; the first available contour at or deeper than the safety setting is emphasized. Group styles are explicit, so changing an individual layer's default style does not alter other presets.

The source path, GDAL executable and cache directory are server-side paths. These store settings require trusted GeoServer administrators. Windows deployments need a compatible native GDAL executable; they have not been tested here.

## Updates and cache lifecycle

For a workspace installed by `enc deploy`, follow [Refresh or restore a source](docs/publishing-guide.md#refresh-or-restore-a-source). The original NOAA demo has a [separate catalogue update procedure](docs/noaa-catalogue-maintenance.md#8-updating-an-existing-catalogue). Use the container engine’s stop/start commands for an ordinary restart. The current demo launcher skips initial NOAA publication when the source registry already contains NOAA. A legacy publication can lack that entry.

Keep each edition's base and update files together. `fetch_noaa.py` extracts every downloaded exchange set into a content-addressed directory, preventing old sidecars from mixing with a new edition. Do not overwrite source files while an import is running.

A store reads a snapshot until it is reopened. Re-run the publisher with the new base path and `--update` to reopen the store, regenerate portrayal and request truncation of both chart-group tile grids. **Re-publish every palette in use.** The cache key includes all base/update bytes, the source path, GDAL version and import recipe. Import errors, cancelled cells, or an applied-update-number mismatch prevent publication. A complete exchange set is still the provider's responsibility; the plugin cannot infer an update that was never delivered.

For a catalogue refresh, prepare a new inventory and immutable source generation from a matching NOAA XML/archive pair, then reopen the store and republish all palettes. Preparation rejects missing active cells, edition/update mismatches and native read failures. For uninterrupted updates use a new versioned workspace and switch clients after validation. Existing source/index files must remain unchanged while their store is open.

Old snapshot files are retained intentionally. Remove obsolete generations only after closing the stores/readers using them. No automatic cache deletion or live NOAA refresh is scheduled. Catalogue selection uses a documented four-times-compilation-scale heuristic with overview cells retained, actual `M_COVR` clipping and deterministic overlap ownership. Very small-scale views can have gaps where no eligible overview chart exists; zoom in to use larger-scale cells. This is not complete ECDIS chart selection. Unscaled WFS queries expose the source features, including overlaps.

## Verify and package

The container demo also precomputes native topology/lookup sidecars for the full catalogue, applies a 2 GiB LRU tile quota, and seeds two bounded operating regions (New York and San Francisco, zooms 11–13, all palettes). `scripts/tune_cache.py` prints its plan by default; changes require `--apply` (including a configuration reload to activate the persisted quota), and seeding additionally requires `--seed`. New demo containers use 6 GiB RAM (`ENC_MEMORY` overrides this), the existing 3 GiB Java heap, and four simultaneous ENC renders (`-Denc.maxConcurrentRenders` overrides this). See [metadata and cache contracts](docs/edge-metadata.md) and [measured results](docs/portrayal-2026-11-17.md).

```bash
# Fetch an additional cell with a real .001 update, then enable native integration tests:
source scripts/env.sh
export S57_TEST_FILE=$(python scripts/fetch_noaa.py US5NY1AI)
scripts/build.sh
python scripts/smoke_test.py
python scripts/package.py
```

For the running national container, run the regional WMS, axis-order and three-palette WMTS checks from its operator container:

```bash
container/operator.sh python3 /opt/enc/scripts/catalogue_smoke.py \
  --url http://127.0.0.1:8080/geoserver --out /opt/enc-cache/enc-smoke
```

Set `S57_CATALOGUE=/absolute/path/catalogue.sqlite` as well as `S57_TEST_FILE` and `OGR2OGR` for native catalogue Java tests. The original [single-cell validation](docs/validation.md) is historical; current national-container results are in [catalogue validation](docs/catalogue-validation.md).

Without `S57_TEST_FILE`, the native cell integration tests are explicitly skipped; other Java and Python tests still run. See [validation evidence](docs/validation.md) for the actual executed checks and limits. `scripts/package.py` builds and tests both Maven targets and writes two installable ZIPs with notices and checksums under `dist/`. The [installation results](docs/plugin-install-validation.json) record the standalone and Cloud image identities and protocol checks.

## Decisions and future formats

- [Design and implementation log](docs/decisions.md)
- [Portrayal coverage and fidelity work](docs/portrayal.md)
- [S-62, S-63 and S-101 options](docs/future-formats.md)
- [Licensing and provenance](NOTICE.md)

S-57 describes ENC data; S-52 describes its presentation. S-62 is the IHO producer-code register, so there is no separate “S-62 ENC” decoder. Producer identifiers are preserved; the future-formats document also covers S-63 encrypted ENCs if that was the intended format.
