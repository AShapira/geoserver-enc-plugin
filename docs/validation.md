# Validation — 2026-11-13

Latest: [November 16 optimization implementation, repeated comparison and resource tests](optimization-2026-11-16.md). The following records the earlier validation.

The implementation was built and run in this workspace. A dedicated GeoServer process listens on loopback port 18080; existing services were not changed. Tests below were actually executed, not proposed.

## Versions and data

| Component | Tested value |
| --- | --- |
| GeoServer / GeoTools | 3.0.2 / 35.2 |
| GDAL | 3.11.5, S57 and GPKG drivers |
| Java | OpenJDK 21.0.10; plugin compiled with release target 17 |
| Maven | 3.9.16 |
| Host | Linux x86_64 |
| Portrayal catalogue | OpenCPN commit `8c8d64570a80e0791e3b7c0a1a88f9315eea09e7` |
| Visual sample | NOAA US5NY1BH, edition 5, update 0, issue date 2025-08-20, compilation scale 1:12,000, depth metres |
| Update sample | NOAA US5NY1AI, edition 5, applied update 1; actual `.000` plus `.001` |

Visual sample download: `https://charts.noaa.gov/ENCs/US5NY1BH.zip`, retrieved 2026-11-13. Archive SHA-256: `844bf0ef6e64d248ee3bbab8305364588dd1e5d39c6e92769b440291d7e80c58`. Its exchange-set issue date is older than the download date; the test does not manufacture a newer edition. Local per-file provenance is under the hash-named `data/noaa/` extraction directory.

The visual sample publishes **40 object classes, 3,464 features including 860 split soundings, 55 ordered style passes**, with 108 generated assets per palette. Source metadata and geometry-bearing metadata layers remain available through the plugin/cache even when not selected for the composed chart.

## Results

- **8 Java tests passed, 0 skipped** with the real update sample: SPI discovery; local base validation; content-based cache invalidation; native process error/timeout handling; filter/sort/offset/limit/property projection; bounds and spatial rejection; namespace; read-only write rejection; snapshot reuse; and missing-intermediate-update rejection. Several checks share a test method.
- **7 Python tests passed**: list matching; exclusive buoy lookup/fallback and SCAMIN; nonoverlapping depth bands/no-data; safety-contour rounding; rendering every pinned vector line/pattern and raster pattern; differing palette symbol pixels; and rejection of non-metre depth units.
- **Live WMS/WMTS/WFS smoke tests passed for day, dusk and night.** The actual WMS 1.1.1 / WMS 1.3.0 EPSG:4326 images were pixel-identical when the correct axis order was used. EPSG:3857 and detail views rendered successfully. Four concurrent overview requests were byte-identical to the baseline.
- For each palette, the same WMTS tile returned **MISS then HIT**, with byte-identical tile contents. The three palettes had different image/tile hashes. WFS returned five point soundings with depth properties.
- Generated images were visually inspected. Actual coastline, depth colours, navigational aids, patterns, soundings and labels are present. This is not a quantitative comparison against a reference ECDIS.
- Re-running the publisher and the end-to-end demo with `--update` succeeded. A new GDAL cache recipe created a new snapshot; the installed JAR was verified byte-identical to the built JAR.
- Bootstrap reuse succeeded; the exact 119-package environment lock resolved in dry-run mode. Original portrayal source checksums were verified. The plugin package is generated with source and license notices.

[Machine-readable results](validation-results.json) contain hashes, test counts, WMS timings and the exact WMTS requests. Observed warm overview requests were below one second in this environment; these are smoke-test observations, not a capacity benchmark.

## Reproduction

```bash
python3 scripts/bootstrap.py
source scripts/env.sh
export S57_TEST_FILE=$(python scripts/fetch_noaa.py US5NY1AI)
scripts/build.sh
scripts/serve.sh  # foreground; use another shell below
```

```bash
export GEOSERVER_PASSWORD=geoserver
scripts/demo.sh  # add --update only for the existing plugin-owned demo workspace
```

The source archive contains the tests, scripts, pinned portrayal inputs and exact environment lock. Generated PNGs and full runtime logs stay local under `evidence/` and `.runtime/`; they can be reproduced with the same exchange set and runtime. NOAA downloads are live and may change, so retain their provenance manifests for a visual regression baseline.

## What is not established

Full S-52/S-64 compliance; accuracy for every ENC object/conditional procedure; seamless labels across every tile/metatile boundary; multi-cell quilting; high-load performance; Windows deployment; Java 17 runtime behavior; S-63 decryption or S-101 decoding; or public deployment/operational suitability. See [portrayal coverage](portrayal.md) for the concrete rendering gaps. GeoServer remains responsible for service authentication and deployment configuration.
