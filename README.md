# GeoServer S-57 ENC plugin

A read-only **GeoServer 3.0.2 / GeoTools 35.2** plugin backed by GDAL's S57 reader. One catalogue store serves the **entire active NOAA ENC catalogue** through WMS and GeoWebCache WMTS. It indexes actual chart coverage, selects cells by scale and clips overlapping coverage. Adjacent updates are applied to immutable, indexed GeoPackage snapshots. Single `.000` stores remain supported.

The supplied portrayal compiler uses pinned OpenCPN S-52 colours, raster symbols, lookup tables, and HPGL patterns/lines. It supplies depth bands, selected safety contours, compound sounding glyphs, light sectors/characteristics, topmarks, formatted labels, scale filtering, and day/dusk/night presets. Versioned [native edge metadata](docs/edge-metadata.md) handles conditional shared-edge priorities, masks, spatial-quality segments and precomputed lookup selection. **Portrayal is experimental and incomplete; this is not an ECDIS implementation or a claim of S-52 conformance.** See [portrayal coverage](docs/portrayal.md) and the [latest OpenCPN comparison and CPU/RAM/disk measurements](docs/portrayal-2026-11-17.md).

## Try the NOAA demo

Run from this directory with Podman and network access:

```bash
container/demo.sh
```

Open **[the interactive chart](http://127.0.0.1:18080/enc.html)**. Switch region, day/dusk/night palette, or WMS/WMTS service. Pan anywhere in NOAA coverage; bookmarks do not limit the catalogue.

The image extends the official vanilla **`docker.osgeo.org/geoserver:3.0.2`** image with this plugin and GDAL tooling. A build stage compiles the plugin against the image's own GeoServer libraries; no host Java, Maven, GDAL or Python environment is required. The first run downloads NOAA's full exchange archive and prepares every active cell. The validated snapshot contains **7,114 active cells, 6,965,828 source features and no failed imports**, from the catalogue valid 2026-11-14. A single current metadata generation uses about **15 GiB** for sources, converted data, edge sidecars and GeoServer state, plus container images; allow at least 25 GiB free. Retained older metadata generations consume additional space. Downloads, imports and first tile renders take time.

The container runs detached as `geoserver-enc`, publishes IPv4 loopback port 18080, has a health check and uses `unless-stopped`. This port was verified from both WSL and Windows localhost. Windows/WSL forwarding still depends on the local WSL configuration. No firewall changes are made. To rebuild after source changes, retaining the catalogue and caches:

```bash
container/demo.sh --recreate
podman logs --tail 50 geoserver-enc
podman stop geoserver-enc
podman start geoserver-enc
```

If an immediate restart reports pasta `Address already in use`, let the old port forwarder exit, then run `podman start geoserver-enc` again. This transient Podman behavior occurred once during validation; the volumes and publication were retained.

`CONTAINER_ENGINE=docker container/demo.sh` selects Docker (the executed validation used Podman). `ENC_PORT=18081` selects another local port when creating a container. An existing container keeps its previous port until `--recreate`.

Three dedicated named volumes retain data: `geoserver-enc-catalogue` (read-only in the server), `geoserver-enc-cache`, and `geoserver-enc-data`. The script preserves them when recreating the server. It reuses an existing inventory; **it does not automatically refresh NOAA data**. The demo retains the official image's initial `admin` / `geoserver` credentials and is intended for local access.

Endpoints:

- Viewer: <http://127.0.0.1:18080/enc.html>
- Admin: <http://127.0.0.1:18080/geoserver/>
- WMS: <http://127.0.0.1:18080/geoserver/wms>
- WMTS capabilities: <http://127.0.0.1:18080/geoserver/gwc/service/wmts?SERVICE=WMTS&REQUEST=GetCapabilities>
- Groups: `noaa:chart_day`, `noaa:chart_dusk`, `noaa:chart_night`.
- WMTS grid sets: `EPSG:4326` and `EPSG:900913` (Web Mercator).

See [full-catalogue validation](docs/catalogue-validation.md), [container build](container/Dockerfile) and [design decisions](docs/decisions.md).

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

For a **lean, source-only offline image build**, use the [air-gap build kit](airgap/README.md).
It defaults to Kartoza GeoServer **2.28.0**, accepts other prepared base images and library paths,
and contains only production sources, required resources, build configuration and notices.
Create the ZIP with `python3 scripts/package_airgap.py`. The [full Kartoza guide](docs/kartoza-2.28.0.md)
also covers the optional chart publisher and the compatibility validation.

1. Use **GeoServer 3.0.2**, Java 17 or 21, and GDAL 3.2+ with S57 and GPKG drivers (tested with 3.8.4 in the container and 3.11.5 in development). Ensure GDAL's data dictionaries and PROJ data are available to the server process.
2. Build with `mvn package`. Copy **only** `target/gs-s57-0.1.0.jar` into `WEB-INF/lib`, then restart GeoServer. The tested GeoServer binary already contains `gt-geopkg` and its dependencies; do not replace GeoTools JARs. If your custom distribution omits them, install its matching GeoPackage support first.
3. Add a store of type **S-57 ENC (GDAL)**, supplying:

| Parameter | Value |
| --- | --- |
| `dbtype` | `s57` |
| `catalogue` | Absolute path to a prepared `catalogue.sqlite`; use this for the full NOAA catalogue |
| `file` | Alternative absolute path to one `.000` file; specify exactly one of `file` and `catalogue` |
| `cache` | Absolute writable cache directory, outside the source exchange set |
| `ogr2ogr` | Absolute path to GDAL's `ogr2ogr` executable |
| `timeout` | Import timeout in seconds; default 300 |
| `namespace` | Optional feature namespace URI |
| `cellPoolSize` | Catalogue JDBC store pool target; default 16, demo 32; active readers remain leased |
| `safetyDepth` | Safety depth in metres, in cell and catalogue modes; default 5; must match the generated portrayal setting |

4. Publish object classes in the GeoServer UI, or use `scripts/publish.py` to generate and install the complete ordered chart group. The publisher requires GDAL Python bindings, Pillow, REST administrator credentials, and filesystem access to the server's data directory for symbol assets. It manages one catalogue or single-cell store per workspace. To prepare a catalogue, download `ENCProdCat.xml` and `All_ENCs.zip` from NOAA, then run:

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

Set `--palette dusk` or `--palette night`, `--styles portrayal/generated-night`, and `--update` to add another preset to an existing plugin-owned workspace. The groups `chart_day`, `chart_dusk`, and `chart_night` have separate tile caches. `--shallow 2 --safety 5 --deep 10` sets fixed metre thresholds; the first available contour at or deeper than the safety setting is emphasized. Group styles are explicit, so changing an individual layer's default style does not alter other presets.

The source path, GDAL executable and cache directory are server-side paths. These store settings require trusted GeoServer administrators. Windows deployments need a compatible native GDAL executable; they have not been tested here.

## Updates and cache lifecycle

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

For the running national container, run the regional WMS, axis-order and three-palette WMTS checks inside it:

```bash
podman exec geoserver-enc python3 /opt/enc/scripts/catalogue_smoke.py \
  --url http://127.0.0.1:8080/geoserver --out /tmp/enc-smoke
```

Set `S57_CATALOGUE=/absolute/path/catalogue.sqlite` as well as `S57_TEST_FILE` and `OGR2OGR` for native catalogue Java tests. The original [single-cell validation](docs/validation.md) is historical; current national-container results are in [catalogue validation](docs/catalogue-validation.md).

Without `S57_TEST_FILE`, the native cell integration tests are explicitly skipped; other Java and Python tests still run. See [validation evidence](docs/validation.md) for the actual executed checks and limits. `scripts/package.py` creates an install ZIP plus source and notices under `dist/`.

## Decisions and future formats

- [Design and implementation log](docs/decisions.md)
- [Portrayal coverage and fidelity work](docs/portrayal.md)
- [S-62, S-63 and S-101 options](docs/future-formats.md)
- [Licensing and provenance](NOTICE.md)

S-57 describes ENC data; S-52 describes its presentation. S-62 is the IHO producer-code register, so there is no separate “S-62 ENC” decoder. Producer identifiers are preserved; the future-formats document also covers S-63 encrypted ENCs if that was the intended format.
