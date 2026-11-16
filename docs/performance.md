# Live performance and resource analysis — 2026-11-15

Latest: [November 16 optimization implementation, repeated comparison and resource tests](optimization-2026-11-16.md). The following records the earlier validation.

The tested service is the running rootless Podman container, built from vanilla GeoServer 3.0.2, with GDAL 3.8.4, the complete 7,114-cell NOAA catalogue and pre-existing GeoPackage snapshots. Final tested image: `791d4acda79974bd8a3dcebed1ecdc47a1b276bac8f4bb2a205d11150918a34a`. The host is a Ryzen 9 9950X3D, with 28 logical CPUs and 47 GiB RAM visible to this WSL2 instance. Other workstation workloads were left running. These are local loopback measurements, not a production capacity guarantee.

## Method

`scripts/benchmark.py` measures 1000×800 WMS PNGs for New York, San Francisco and the continental overview; 256×256 WMTS tiles; and four concurrent identical WMS requests. Each WMS case has a separate initial request, then three baseline repetitions or five final repetitions. WMTS uses 100 sequential cache hits. Container cgroup CPU, anonymous/file memory, Java RSS and `/proc/1/io` counters are sampled every 250 ms. CPU 100% means one logical core, not the entire 28-CPU host. Latency excludes the final sampling wait; CPU windows include it and a small sampling-process cost.

No OS cache was dropped, no forced GC was run, no catalogue reconversion was included, and no unrelated services were stopped. Two consecutive final passes expose run-to-run variability. A separate JFR profile is diagnostic only: its timing/CPU numbers are excluded from the table because recording/JIT and a concurrent build affected that run. Baseline and optimized runs use separate JVM lifetimes, so differences are not controlled causal estimates.

Raw measurements: baseline (`../evidence/performance/before/results.json`; local generated evidence), geometry-only optimization (`../evidence/performance/geometry-optimized/results.json`; local generated evidence), final first pass (`../evidence/performance/final-first/results.json`; local generated evidence), final repeat (`../evidence/performance/final/results.json`; local generated evidence), WMTS miss/hit (`../evidence/performance/wmts-miss-hit.json`; local generated evidence). Every case records the URL, latency, hash, bytes and resource counters. Adjacent `samples.json` files retain the time series.

## Latency and CPU

| Request | Original median | Geometry-only median | Revised portrayal, two pass medians | Revised CPU seconds/request, repeat |
| --- | ---: | ---: | ---: | ---: |
| New York WMS | 1.709 s | 1.560 s | 1.563–2.028 s | 2.68 |
| San Francisco WMS | 1.575 s | 1.521 s | 1.934–2.067 s | 2.50 |
| Continental WMS | 1.251 s | 0.960 s | 1.200–1.209 s | 1.82 |
| WMTS cache hit | 2.9 ms | 2.6 ms | 1.5–1.7 ms | ~0.004 |

The geometry-only change preserved **identical PNG SHA-256 hashes** in all measured cases. Observed latency reductions were about 9%, 3% and 23% respectively. CPU did not consistently decrease in that run; JVM warm-up and sampling variability prevent claiming a CPU saving.

The richer final portrayal adds more text, native symbols and coastline-priority processing. San Francisco is slower than the original; New York varies around and above the original. The continental case remains slightly faster. Do not describe the full change as an across-the-board speedup.

The final repeat used approximately 124%, 119% and 140% CPU during the sequential WMS cases, predominantly one rendering core plus JVM/background work. Four simultaneous New York requests completed in 2.08–2.11 s, around 1.9 requests/s aggregate, with identical PNG hashes. This small burst does not establish sustained multi-user capacity, a p95/p99, or a safe maximum concurrency.

A separate zoom-14 tile returned **MISS in 3.180 s**, then **HIT in 3.65 ms**, with identical image hashes. This is a tile-cache miss with warm source/OS caches, not a cold-machine measurement. A 4×4 metatile is rendered on the miss, so it cannot be compared directly with one 256×256 WMS render.

## Memory

- Original Java RSS was about 1.80 GiB and container memory about 1.79 GiB. RSS and cgroup totals account shared pages differently; neither should be added to the other.
- Final Java RSS peaked around **2.11 GiB** in the repeat; container memory was approximately **2.46 GiB**, with about **0.31 GiB file cache** at idle. Across the first pass, the container peak was **2.53 GiB**.
- Final heap snapshot: roughly **1.10 GiB used / 1.23 GiB committed**, with `-Xmx3g`; metaspace about 122 MiB. This is a point-in-time snapshot, not live-data size after GC or a leak test.
- Idle CPU was approximately **0.7–0.8% of one core**. Full chart data remains on disk; it is not loaded wholesale into Java heap.
- The plugin's compound-symbol LRU is capped at 512 icons: at most about 78 MiB of raw pixels if every entry were a 200×200 light graphic, normally much less. The three source atlases require about 21 MiB of raw pixels. This is not a bound on total renderer memory or GeoTools' own caches.
- Prepared coverage selections are retained for 128 query keys, up from 24. Cell readers target 32 retained leases in the demo; active readers can temporarily exceed that target. Topmark/coastline context and derived boundaries are cached per retained cell. Greater concurrency or very complex cells can increase memory beyond this sample.

## Disk and I/O

| Component | Measured allocated size |
| --- | ---: |
| NOAA archive, exchanges and inventory | 2.14 GiB |
| 7,114 preconverted cell snapshots | 10.01 GiB |
| GeoServer data, styles, logs and current tiles | about 100 MiB |
| Plugin container image, uncompressed logical size | 1.05 GiB |
| Vanilla image portion, shared container layers | 0.85 GiB |
| Separate development `.runtime` checkout/tools/downloads | 5.09 GiB |

Do not add the whole vanilla image again: its layers are shared. The OpenCPN reference image is a separate development aid, not part of the deployed GeoServer image. Existing old image layers and workstation projects are also outside the three application volumes.

The warmed repeat read only 0–16 KiB of physical disk data per WMS case according to Java's `/proc/1/io`, despite substantial logical reads. Cached source pages explain this; it does **not** prove low disk demand on cold startup or after OS-cache eviction. WMS case writes were approximately 348–360 KiB, largely service logging/background work. WMTS hits recorded zero physical reads/writes in their short measured window. These counters cover Java, not historical GDAL import work. Current data-directory logging is unusually verbose for performance use.

The workspace filesystem had about 150 GiB free at measurement time (87% used overall). No old image, snapshot generation, source file or persistent volume was deleted. Whole-catalogue preconversion speeds first use but costs the 10 GiB cache; on-demand conversion remains supported.

## Bottlenecks and optimization priorities

The baseline JFR showed repeated JTS geometry intersection/relate work. The implemented optimization prepares immutable coverage geometries and retains enough selection entries for the many different style-buffer envelopes in one viewport. Actual clipping still uses robust geometry overlays. Output was byte-identical before portrayal changes.

The final JFR hotspot summary (`../evidence/performance/final/hotspots.json`; local generated evidence) contains 357 execution samples. JTS intersection/noding/spatial-index methods remain prominent, along with WKB decoding, collection growth, string hashing and GeoTools filter/style duplication. The recording is available as `evidence/performance/final/profile.jfr`; sample counts are evidence of likely hotspots, not precise wall-time attribution.

Recommended next steps, in order:

1. **Use WMTS for interactive browsing and preseed the expected operating regions/zoom bands/palettes.** The measured hit/miss difference is the largest practical gain. Set a tile-cache disk quota and expiration policy. Do not preseed the entire world at harbour zooms; tile count grows by four per zoom level.
2. **Prepare native shared-edge portrayal metadata at catalogue import.** Preserve S-57 `RETURN_LINKAGES`/`RETURN_PRIMITIVES`, join Edge endpoints to ConnectedNode, and retain MASK/quality plus edge ownership. This can replace repeated coastline unions/differences while improving fidelity. Store it in versioned, indexed sidecars keyed to the immutable cell fingerprint; do not silently reinterpret old caches. [GDAL documents these options and the missing Edge endpoint coordinates](https://gdal.org/en/stable/drivers/vector/s57.html).
3. **Reduce repeated class scans and style/filter work.** Profile a request-scoped cache of selected/clipped features shared by priority passes, and precompute simple portrayal codes rather than many nested regular-expression filters. Key any cache by cell generation, viewport, scale and settings; cap bytes. Validate pixel identity where semantics should be unchanged.
4. **Control concurrency and memory deliberately.** For a similar small deployment, begin testing with 4–8 render workers and a 4–6 GiB container memory allowance around the existing 3 GiB Java heap; this is a proposed starting configuration, not one applied here. Measure sustained p95 latency and GC before increasing it. JDBC pools are per cell, so multiplying render threads can multiply connections and native/page-cache demand.
5. **Reduce production logging and measure a real cold start separately.** Use a normal GeoServer production logging profile, keep sources/cache on local SSD, and benchmark import, first render and warm render independently. Do not flush shared workstation caches merely to obtain a cold result.
6. **Budget storage by purpose.** Retain all 7,114 snapshots when nationwide first-use latency matters, or warm a documented subset when disk is constrained. Bound GWC storage. Retire only confirmed-unused old image/cache generations after review; no broad pruning is part of this change.

No CPU affinity, kernel, host-cache, GPU, firewall, global container-engine or unrelated-service settings were changed. This rendering path is CPU based; the workstation GPU is not used by GeoServer WMS.
