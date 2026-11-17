# Conditional priorities and spatial quality — 2026-11-17

The [local demo](http://127.0.0.1:18080/enc.html) now serves the complete 7,114-cell NOAA catalogue with conditional restriction/safety priorities and native spatial-quality rendering. The official GeoServer 3.0.2 image remains the base; only the plugin, GDAL and supporting tools are added. The catalogue is the retained NOAA inventory valid 2026-11-14, with numbered updates applied. This work improves selected S-52 procedures; it does not establish ECDIS/S-52 conformance.

The seven-scene [interactive OpenCPN comparison](../evidence/portrayal-2026-11-17/comparison.html) and all raw measurements are local generated evidence, included in the distribution ZIP. They are intentionally ignored by Git. [Decision log](decisions.md), entries 61 onward; [metadata contract](edge-metadata.md); [historical November 16 measurements](optimization-2026-11-16.md).

## What changed

- **Conditional edge ownership and drawing order agree.** RESARE02 restrictions 1–8 or 14 promote the applicable lookup to priority 6. Safety DEPCNT and qualifying line DEPARE contours use priority 8 and bypass SCAMIN. The next available deeper contour is resolved per cell and fixed store safety preset. `_enc_priority` and `_enc_safety` control the same decisions in edge ownership and global SLD passes. Single-cell stores now honor `safetyDepth` too. The catalogue publishes 137 classes in 171 passes, up from 168.
- **Quality follows each native spatial component.** After masking, ownership and orientation, linework is partitioned into normal and low-accuracy geometries. QUAPOS 2–9 selects unreliable positioning; absent values, 1, 10 and 11 keep normal portrayal. QUAPOS/QUALIN coastline and SLCONS conditionals use LOWACC21; contours use dashed DEPCN/DEPSC. Direct LS lookups, including marsh coastline, keep their prescribed stroke. SLCONS now also follows CONDTN/CATSLC/WATLEV and COALNE honors conspicuous-radar under-strokes.
- **Point accuracy is no longer lost at import.** Qualified IsolatedNode/ConnectedNode geometries retain their feature association. A coordinate index resolves each expanded SOUNDG point independently. PA/PD/REP/LOWACC01 point symbols and sounding/wreck-depth qualifiers use `_enc_quapos`. POSACC remains quantitative metadata, without an invented uncertainty radius.
- **Cache behavior stays bounded.** New immutable sidecars retain settings-independent inputs; each store resolves its own safety preset. The 4 MiB assembled-geometry LRU shares uniform-quality geometry objects. Quilt clipping reuses identical geometry within a feature. Unscaled requests have a separate cache band, and source-dependent fallback geometries are not cached under RCID alone.

The importer created **7,114 sidecars in 192.9 seconds**. The independent full audit passed in **10.794 seconds**, with zero corrupt files, dangling edge/point links or unmatched lookups. This used warm source files; it is not a cold-disk importer benchmark.

| Audited metadata | Count |
| --- | ---: |
| Native edges | 4,148,511 |
| Native feature records | 3,854,646 |
| Ordered edge links | 13,965,547 |
| Unreliable edges, QUAPOS 2–9 | 459,339 |
| Qualified point-primitive associations | 79,177 |
| Restriction-priority promotions | 5,230 |
| Contour candidates | 552,883 |

[Full audit](../evidence/portrayal-2026-11-17/edge-audit.json), [prewarm log](../evidence/portrayal-2026-11-17/prewarm.log), [live quality checks](../evidence/portrayal-2026-11-17/live-quality-check.json). The live checks verify geometry partition lengths, safety/restriction priorities and point qualifiers through GeoServer, across the three comparison cells. The test suite passes **28 Java and 15 Python tests, zero skips**, including actual GDAL NOAA imports and synthetic mixed-quality, mask, orientation, SCAMIN and safety-setting cases.

## OpenCPN comparison and deliberate differences

All seven OpenCPN 5.12.4 screenshots were captured again. Both renderers use US5NY1BH edition 5/update 0, US5CA1CK 1/0 and US5CA6EE 1/4, with identical numbered-file hashes, palettes, 2/5/10 m thresholds, registered projection/extent and 1278×936 images. Requested and saved reference settings are retained. The first six baseline images came from the previous live deployment before replacement. For the added quality close-up, the previous image was recreated temporarily with an isolated tmpfs data directory and container-local cache. [Provenance](../evidence/portrayal-2026-11-17/provenance.json).

The **quality** scene deliberately overscales US5CA1CK at 2 pixels per projected metre to expose four QUAPOS=4 coastline edges (103, 104, 108, 109). It is a diagnostic close-up, not a recommended chart viewing scale. Most qualified New York coastlines use the marsh-specific direct dashed lookup, so the original six scenes alone were insufficient to inspect LOWACC21. [Enlarged quality detail](../evidence/portrayal-2026-11-17/quality-closeup.png), [feature/lookup counts](../evidence/portrayal-2026-11-17/corpus-metadata.json).

| Scene | Before agreement | Revised agreement | Before MAE | Revised MAE |
| --- | ---: | ---: | ---: | ---: |
| day | 76.910% | 76.939% | 14.835 | 14.858 |
| detail | 83.909% | 83.918% | 9.581 | 9.587 |
| dusk | 84.638% | 84.544% | 3.236 | 3.275 |
| night | 85.122% | 85.047% | 3.493 | 3.521 |
| sectors | 84.120% | 84.147% | 8.884 | 8.859 |
| light | 89.001% | 89.067% | 7.490 | 7.450 |
| quality | 94.872% | 94.909% | 2.385 | 2.358 |

Agreement means every RGB channel differs by no more than 12; MAE uses the 0–255 range. The existing fixed control/margin masks remain unchanged; the San Clemente light view also excludes area outside its ENC. Gains are small and dusk/night agreement slightly regresses. These are screenshot differences, not a conformance score or evidence that every visual gap is closed. Labels, patterned-area placement and contextual hazards still dominate visible discrepancies.

There are deliberate reference differences. OpenCPN comments out the safety-contour priority-8 change, whereas this implementation applies it. Its legacy SLCONS code names LOWACC01, whose bundled *line* definition is safety-contour coloured; the coastline/construction definition is LOWACC21. Its generic point LOWACC03 name is absent from the pinned library, so the defined LOWACC01 point symbol is used. The parser also repairs one known missing CS parenthesis in the pinned LNDARE point lookup without modifying upstream assets. These choices are recorded against the [pinned OpenCPN procedures](https://github.com/OpenCPN/OpenCPN/blob/Release_5.12.4/libs/s52plib/src/s52cnsy.cpp), the [public IHO Presentation Library draft](https://legacy.iho.int/iho_pubs/draft_pubs/PresLib_e4.0.0/Part_I/S-52_PresLib_e4.0.0_Part%20I_Redline.pdf) and [IHO's quality-display working paper](https://legacy.iho.int/mtg_docs/com_wg/S-100WG/S-100WG3/S-100WG3_6.9.2_Methodology_for_the_display_of_quality_information.pdf). Those public drafts/papers are supporting references, not a claim of validation against the complete current Presentation Library.

## Performance, CPU and RAM

Measurements use the same 1000×800 full-catalogue WMS views and 256×256 WMTS tile. Each warm WMS median contains five calls, following an initial call. Two after passes and a separate load run are retained. Imports, the OpenCPN capture, temporary baseline server and profiler were excluded from timed runs. Host page caches were not flushed. Runtime limits remain four simultaneous ENC renders, 32 retained cell leases, a 3 GiB Java heap, 6 GiB container memory and a persisted 2 GiB GWC tile quota.

| Case | Previous deployment | Revised pass 1 | Revised pass 2 |
| --- | ---: | ---: | ---: |
| New York | 1544.84 ms | 1583.86 ms | 1587.57 ms |
| San Francisco | 1477.89 ms | 1907.75 ms | 1544.19 ms |
| Continental overview | 905.13 ms | 981.56 ms | 965.23 ms |
| WMTS HIT | 1.57 ms | 1.56 ms | 1.37 ms |

The repeated pass is roughly 3% slower in New York, 4% in San Francisco and 7% in the overview. The first San Francisco pass is slower still; JVM/store/render caches differ. There is no established WMS speedup. Cached WMTS remains around 1–2 ms. An actually unseeded zoom-14 tile returned **MISS in 2.324 s**, followed by approximately 1.37 ms hits.

Cgroup CPU seconds across each set of five warm WMS calls, including sampling boundaries and background service work:

| Case | Before | Revised pass 1 | Revised pass 2 |
| --- | ---: | ---: | ---: |
| New York | 11.51 | 8.95 | 9.13 |
| San Francisco | 9.09 | 11.32 | 8.68 |
| Continental overview | 5.60 | 7.13 | 6.33 |

**160 requests at eight clients** completed in **65.69 s**, at **2.44 requests/s**, median **3.258 s**, p95 **3.385 s**. All image hashes matched; no request failed. This consumed **316.2 CPU-seconds**, averaging **4.81 cores**. Load peak was **2.12 GiB container memory / 1.80 GiB Java RSS**. These are workload-specific observations, not a capacity guarantee or a long-running leak test.

The wider region checks and separate JFR run increased the observed container peak to approximately **2.53 GiB**. Memory-limit/OOM counters stayed zero. A subsequent 60-second quiet interval averaged **2.03% of one CPU core**, including quota monitoring and health checks. Short WMTS sampling windows are too brief for credible per-request CPU attribution.

[Before](../evidence/portrayal-2026-11-17/performance-before/results.json), [after](../evidence/portrayal-2026-11-17/performance-after/results.json), [repeat](../evidence/portrayal-2026-11-17/performance-repeat/results.json), [load](../evidence/portrayal-2026-11-17/performance-load/results.json), [idle](../evidence/portrayal-2026-11-17/idle-60s.json).

## Disk and next optimizations

| Component | Size |
| --- | ---: |
| NOAA catalogue/source volume | 2.14 GiB |
| Existing GeoPackage snapshots | 10.00 GiB |
| Required current metadata generation | 2.36 GiB |
| Two retained superseded metadata generations | 4.62 GiB |
| Whole snapshot/metadata cache volume | 16.99 GiB |

The new metadata adds approximately **50.1 MiB** versus the previous required generation. Old generations are retained for rollback, not needed for normal rendering. The tile quota does not cap source/snapshot metadata. [Storage details](../evidence/portrayal-2026-11-17/storage.json) include tile/data-directory sizes, image size and host capacity. Revised warm WMS physical reads were zero, while logical reads continued. The previous deployment still recorded approximately 17.6/8.1/3.8 MiB of physical reads across its New York/San Francisco/overview repetitions. Different OS/JVM cache histories limit causal before/after conclusions; no caches were deliberately flushed.

The separate [JFR summary](../evidence/portrayal-2026-11-17/profile/hotspots.json) contains 1126 execution samples: 609 include JTS, 825 the catalogue reader, 137 JDBC and 3 EdgeContext. These overlap and many recorded stacks are truncated; they are not time percentages. Four waiting render callers were captured, confirming admission control. Topology discovery is not the dominant sampled work.

Next, measure request-scoped reuse of immutable clipped geometry across the additional priority passes and reduce repeated JDBC feature decoding. Keep byte bounds and compare image hashes before retaining such a cache. Expand WMTS preseed only for known operating areas within the disk quota. Superseded metadata can reclaim about 4.62 GiB after an explicit retention decision; no persistent files were pruned here. Increasing heap or render concurrency is not justified by this test alone.

All nine regional WMS views, WMS 1.1/1.3 axis equivalence and three WMTS palette checks pass. The demo is reachable from Windows localhost as well as WSL. Remaining fidelity work includes surrounding-depth isolated-danger promotion, complete obstruction/wreck area and quality procedures, modern viewing-group controls, labels and complex-line corner/pattern calibration.
