# Implemented optimizations and repeated validation — 2026-11-16

The full NOAA catalogue remains available in the [local container demo](http://127.0.0.1:18080/enc.html). Native shared-edge metadata, precomputed portrayal lookups, bounded edge-geometry caching, spatial-filter pushdown, selective WMTS preseed, disk quotas and render/memory controls are implemented. Warm WMS latency is broadly unchanged in this workload. The principal operational gain is predictable cached WMTS access; native metadata removes the old approximate coastline overlay path and preserves topology needed for further portrayal work.

See the interactive OpenCPN comparison (`../evidence/optimization-2026-11-16/comparison.html`; local generated evidence), [metadata contract](edge-metadata.md), and [decision log, entries 46 onward](decisions.md). The November 15 reports remain historical records.

## Complete-catalogue preparation

The retained NOAA inventory contains **7,114 cells**, from the catalogue valid 2026-11-14. Both the original immutable GeoPackage snapshots and all numbered updates remain intact. Final sidecar revision is `5989f703d6305e27`. The final four-worker prewarm completed in **232.4 seconds**, creating 7,113 sidecars and reusing one already built by a reference request. An independent full audit passed for every expected cell, checking source fingerprints, SQLite integrity and both edge/feature linkage relationships.

| Metadata | Count |
| --- | ---: |
| Complete native edges | 4,148,511 |
| Native feature lookup records | 3,854,646 |
| Ordered feature-to-edge links | 13,965,547 |
| MASK=1 links | 8,414 |
| Edges with QUAPOS or POSACC | 459,963 |
| Unmatched portrayal lookups / audit errors | 0 / 0 |

Native feature records differ from the expanded GDAL feature count because soundings can expand into multiple points. Full evidence: audit (`../evidence/optimization-2026-11-16/edge-audit-final.json`; local generated evidence), prewarm log (`../evidence/optimization-2026-11-16/edge-prewarm-final.log`; local generated evidence). Prewarm timing is not a cold-disk benchmark and does not establish importer CPU/RAM peaks.

## Applied runtime settings

| Setting | Applied value |
| --- | --- |
| ENC render admission | Four concurrent renders; fair queue; 30-second queue timeout |
| Container memory / Java heap | 6 GiB / existing `-Xmx3g` |
| Derived edge-geometry LRU | Estimated 4 MiB per retained cell, keyed by feature and SCAMIN band |
| Retained cell-store target | 32; active leases may temporarily exceed it |
| GWC quota | 2 GiB, LRU, one cleanup worker every 60 seconds |
| Tile expiration | Seven days on server; one hour in clients |
| WMS rendering timeout | 120 seconds |
| Logging | `PRODUCTION_LOGGING` |
| Default preseed | New York and San Francisco extents; zooms 11–13; day/dusk/night |

The seed plan contains **246 requested tiles**, at most **816 generated tiles** after 4×4 metatile expansion. Six sequential seed jobs completed in about **119 seconds**; all 246 requested tiles were subsequently verified as **HIT**. Seed timing overlaps other validation work and is not an isolated throughput benchmark. The quota is persisted and verified after container recreation. Eviction at the 2 GiB threshold was not stress-tested. Cleanup is asynchronous, so this is not a hard byte ceiling. It bounds generated tiles, not source charts, snapshots, sidecars, logs or container images. Persisted configuration (`../evidence/optimization-2026-11-16/tuning-persisted.json`; local generated evidence), restart verification (`../evidence/optimization-2026-11-16/deployment.json`; local generated evidence), seed jobs (`../evidence/optimization-2026-11-16/tuning-seed.json`; local generated evidence), every tile check (`../evidence/optimization-2026-11-16/seed-verification.json`; local generated evidence).

## Latency and CPU

The comparison uses vanilla GeoServer 3.0.2 plus the plugin, GDAL 3.8.4 and the same full catalogue on this Ryzen 9 9950X3D WSL2 workstation. WMS PNGs are 1000×800; WMTS tiles are 256×256. Each WMS value is the median of five measured calls after a separate initial call. WMTS uses 100 hits. Two consecutive final passes show run-to-run variation. Imports, OpenCPN and image builds were stopped during the measured runs; unrelated workstation services were left running.

| Request | Before | After, pass 1 | After, pass 2 |
| --- | ---: | ---: | ---: |
| New York WMS | 1.4628 s | 1.5451 s | 1.4307 s |
| San Francisco WMS | 1.4589 s | 1.4714 s | 1.4502 s |
| Continental overview WMS | 0.8990 s | 0.8926 s | 0.8733 s |
| Seeded WMTS HIT | 0.0017 s | 0.0023 s | 0.0016 s |

The unseeded zoom-15 tile returned **MISS in 0.998 seconds**, followed by roughly **1.64 ms hits**. Preseed therefore avoids an expensive first render in the selected regions; it does not make arbitrary uncached viewports equally fast.

The first New York request after the final JVM restart took **7.161 seconds**. Its files were already present and the OS page cache was warm. This is a JVM/store-first-use observation, not a cold-machine result. The old container's initial request took 5.982 seconds, but its prior store/JIT state differed; those initial observations are not a controlled speed comparison.

Cgroup CPU seconds across the five warm calls, including service background activity and sampling boundaries:

| WMS case | Before | After, pass 1 | After, pass 2 |
| --- | ---: | ---: | ---: |
| New York | 9.65 | 13.47 | 8.06 |
| San Francisco | 8.91 | 10.28 | 8.81 |
| Overview | 6.52 | 6.51 | 5.80 |

There is **no established across-the-board WMS speedup or CPU reduction**. The first pass costs more CPU in New York/San Francisco; the repeated pass costs less. CPU 100% means one logical core. Subsecond WMTS sample windows are too short to isolate request CPU from JVM/GWC background work. Baseline sampling also included four old lightweight sampling processes, discovered and removed by container replacement; the benchmark now explicitly terminates its in-container sampler. Three-second idle samples ranged from 0.54–13.77% of one core, including a short background-work burst. A separate 60-second steady-idle sample (`../evidence/optimization-2026-11-16/idle-60s.json`; local generated evidence), with health checks and quota monitoring enabled, averaged **0.73% of one core**.

At eight clients, **160 consecutive New York requests** completed in **60.33 seconds**, at **2.65 requests/s**. Median latency was **2.997 seconds**, p95 **3.059 seconds**; all image hashes matched, with no request errors. This used **292.8 CPU-seconds**, averaging about **4.85 cores**, including JVM/background work. A separate diagnostic thread dump captured **four requests waiting at the ENC semaphore**, confirming that the admission limit was active. This one-minute single-viewport test is not a long-running leak test or a capacity guarantee for every chart/viewport.

Raw runs: before (`../evidence/optimization-2026-11-16/performance-before/results.json`; local generated evidence), after (`../evidence/optimization-2026-11-16/performance-after/results.json`; local generated evidence), repeat (`../evidence/optimization-2026-11-16/performance-repeat/results.json`; local generated evidence), 160-request load (`../evidence/optimization-2026-11-16/performance-load/results.json`; local generated evidence).

## RAM, disk and remaining hotspots

The 160-request load peaked at **1.45 GiB container memory** and **1.45 GiB Java RSS**. After the broader nine-region validation and diagnostic JFR, the container's lifetime peak was **1.66 GiB**; all cgroup memory-limit and OOM counters remained zero. The linked post-validation heap snapshot records used and committed heap against the configured 3 GiB maximum. Anonymous memory and file cache are reported separately in the raw evidence. The baseline warm cases reached about 2.76 GiB container memory and 2.30 GiB RSS, but JVM age, GC state, logging and resource configuration differ, so this is not a causal memory-saving estimate. Post-validation snapshot (`../evidence/optimization-2026-11-16/post-validation-resources.json`; local generated evidence).

| Storage component | Size |
| --- | ---: |
| NOAA source archive, exchanges and catalogue | 2.14 GiB |
| Existing GeoPackage snapshots | About 10.01 GiB |
| Required current edge metadata | **2.31 GiB** |
| Superseded development metadata, retained separately | **2.31 GiB** |
| Entire current cache volume, including both generations | About 14.63 GiB |
| Generated tile cache after verification | About 18.2 MiB |

A normal fresh installation needs only the current metadata generation. The extra development generation is not required by the renderer; it was retained to avoid silently pruning persistent host storage. No source data, existing snapshots, unrelated images or volumes were deleted. The 2 GiB tile quota does not cap the 14.63 GiB data cache. The image is approximately 1.05 GiB uncompressed, with its vanilla base layers shared; development tools, the reference image and old image layers are additional storage.

Warm measured Java physical reads were zero in these cases, while logical reads continued. Writes were 0–16 KiB per warm WMS case after production logging was applied, versus roughly 0.3 MiB in the earlier configuration. OS caching explains the low physical I/O; no host caches were flushed.

A restart check found that GWC 2.0.2 quota PUT changes only its in-memory bean. The helper now persists XML through the resource API and reloads the dedicated instance. The final benchmark runs reported here use the persisted configuration; earlier runs are retained under `intermediate-without-persisted-quota`. [Upstream controller](https://raw.githubusercontent.com/GeoWebCache/geowebcache/2.0.2/geowebcache/diskquota/core/src/main/java/org/geowebcache/diskquota/rest/controller/DiskQuotaController.java).

The separate JFR summary (`../evidence/optimization-2026-11-16/profile/hotspots.json`; local generated evidence) has **443 execution samples**. **228** contain JTS frames, **324** contain the catalogue reader and **70** contain GeoTools JDBC frames; these categories overlap and are not elapsed-time attribution. The old `BoundaryContext` is removed. Coverage clipping/geometry predicates, geometry decoding, JDBC metadata and Java2D rendering remain material work. A full mutable-feature cache has not been introduced: differing style-buffer envelopes and geometry mutation/copying costs need measurement before accepting that memory tradeoff. Next targeted work is to measure reuse of immutable clipped geometry within one request and JDBC metadata caching, while retaining byte bounds and pixel-equivalence checks. Do not increase render concurrency or heap solely from this one-minute result.

## OpenCPN comparison

Six actual OpenCPN 5.12.4 screenshots were recaptured against the same NOAA cells: US5NY1BH (edition 5/update 0), US5CA1CK (1/0), and US5CA6EE (1/4, including `.001`–`.004`). Numbered-file hashes match provenance (`../evidence/optimization-2026-11-16/provenance.json`; local generated evidence). The harness now rebuilds the chart database, exits, restores an off-chart own-ship position, and restarts without rebuilding. It also restores full-precision viewport coordinates after OpenCPN's rounded configuration save. Requested, rendering-requested and actual settings are retained with each screenshot.

The WMS extent, projection, pixel dimensions, palette and safety settings are registered to each reference. Fixed masks exclude viewer controls/margins and the San Clemente area outside the ENC. The before images are fresh captures of the previous deployment, compared with the same newly captured references as the after images. Agreement means every RGB channel is within 12; MAE is on 0–255 RGB values.

| Scene | Before agreement | After agreement | Before MAE | After MAE |
| --- | ---: | ---: | ---: | ---: |
| day | 76.913% | 76.910% | 14.833 | 14.835 |
| detail | 83.911% | 83.909% | 9.582 | 9.581 |
| dusk | 84.639% | 84.638% | 3.235 | 3.236 |
| night | 85.122% | 85.122% | 3.492 | 3.493 |
| sectors | 84.099% | 84.120% | 8.904 | 8.884 |
| light | 88.957% | 89.001% | 7.503 | 7.490 |

The native-edge change is visually close to the previous implementation. The California scenes improve slightly; New York changes are negligible and include tiny regressions. Day magenta pixels remain **800 versus 3,499** in OpenCPN, and detail remains **230 versus 2,140**. Native topology and masks alone do not fix conditional priority promotion, symbol/label placement or full spatial-quality portrayal. Those gaps remain explicit; this is **not an S-52/S-64 compliance score**. Full images and measurements (`../evidence/optimization-2026-11-16/comparison.html`; local generated evidence).

## Verification and reproduction

**26 Java tests and 12 Python tests passed, with no skipped native integration tests.** Tests cover connected-node endpoints, empty intermediate edges, masks, orientation, scale-dependent ownership, lookup/null/list matching, filled-area ownership, cache revision and render-permit release. The full metadata audit, nine-region WMS smoke, three WMTS palettes and byte-identical WMS 1.1/1.3 axis-order test passed. Windows localhost returned HTTP 200 for the viewer and an actual WMS PNG; this verifies forwarding, not a Windows-native GeoServer deployment.

```bash
source scripts/env.sh
export S57_TEST_FILE="$PWD/.runtime/noaa-catalogue/exchanges/1d61c657968ac6c338cc/ENC_ROOT/US5NY1AI/US5NY1AI.000"
export S57_CATALOGUE="$PWD/.runtime/noaa-catalogue/catalogue.sqlite"
./scripts/build.sh
python scripts/benchmark.py --repeat 5 --sustained-requests 160 --concurrency 8 --miss-probe --out evidence/recheck
python scripts/catalogue_smoke.py --out evidence/recheck-catalogue
python scripts/compare_portrayal.py --root evidence/optimization-2026-11-16
```

The MISS probe reports the actual header: a repeat run may find that tile already cached. `container/demo.sh --recreate` rebuilds/redeploys while retaining named volumes, warms all metadata and applies the bounded seed plan. The OpenCPN capture script requires the separately initialized reference container and Xvfb. It is not a server runtime dependency.
