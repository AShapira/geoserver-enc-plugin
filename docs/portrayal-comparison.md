# OpenCPN comparison — 2026-11-15

Latest: [November 16 optimization implementation, repeated comparison and resource tests](optimization-2026-11-16.md). The following records the earlier validation.

Open the interactive before/reference/after comparison (`../evidence/portrayal/comparison.html`; local generated evidence) in a browser. Raw PNGs, full screenshots, requested/saved OpenCPN configuration, exact WMS URLs and numeric results (`../evidence/portrayal/comparison.json`; local generated evidence) are retained together. No reference chart image was reconstructed or edited to resemble the plugin; the only image operation is the documented canvas crop.

## Reference and registration

- Unmodified Ubuntu package `opencpn 1:5.12.4+dfsg-1`, in a separate rootless container built from `container/opencpn-reference.Dockerfile`. The image uses Ubuntu 26.04; package version was recorded, but apt repositories are not an immutable package lock.
- OpenCPN source inspected at `Release_5.12.4`, commit `37fd0cddb7334fe489e9f18aa163977a9c5c84f7`. See [conditional procedures](https://github.com/OpenCPN/OpenCPN/blob/Release_5.12.4/libs/s52plib/src/s52cnsy.cpp). The existing pinned portrayal resources remain unchanged. The reference's installed day atlas has different PNG encoding but identical decoded RGBA pixels; the XML differs, including additional unused high-contrast palettes in our pinned copy.
- Xvfb 1280×960 at 96 dpi, software rendering (`opencpn -G -f`), fullscreen. Canvas crop `(1,0,1279,936)` gives 1278×936. Display size 358 mm, default ChartTexts Sans 10, simplified symbols, plain boundaries, all display categories, soundings and SCAMIN enabled, decluttering enabled. Shallow/safety/deep depths 2/5/10 m; four depth shades. AIS disabled and own ship moved to 0,0 in the reference configuration.
- Single-cell rendering, quilting disabled, to isolate portrayal from chart-selection differences. Full NOAA catalogue operation is tested separately. Each reference chart directory contains the same immutable exchange files as the GeoServer store.
- Mercator viewport matches the requested centre and pixels/metre, including OpenCPN's `mercator_k0=0.9996`. WMS uses EPSG:3857 and `SCALEMETHOD=Accurate`, which matches the ground-scale interpretation used for this comparison. Generic WMS/WMTS scale behaviour is unchanged.
- OpenCPN saves rounded centre coordinates after exit; `scene.json` records the higher precision requested for the actual capture. Default extended light-sector setting was requested off but OpenCPN saved it on. The native plugin uses bounded 25 mm sector legs; this difference is retained in the evidence.

| NOAA cell | Views | SHA-256 of identical `.000` input |
| --- | --- | --- |
| US5NY1BH | Day, dusk, night at 0.15 px/projected m; sounding detail at 0.4 | `c752c713d5fb50bca0f1855039acdce57571f2308cf0523b03ab75b5836ba93e` |
| US5CA1CK | San Clemente Island, 0.2; two extinguished sector-light records | `2daf86631e9f80556a74cead64d5a792b0fc13c49c319172ed34e4c8ec2f760d` |
| US5CA6EE | Humboldt Bay, 0.35; active sector/range lights, soundings, dredging | `ab0015aa6997c9a37d64196e0800d31be9ad217bae8efdd8c8b3e1b4fb039a7e` |

NOAA inventory date is 2026-11-14. US5NY1BH is edition 5/update 0; US5CA1CK is edition 1/update 0. US5CA6EE is edition 1/update 4, with `.001`–`.004` updates present in the same read-only directory used by both renderers. Provenance (`../evidence/portrayal/provenance.json`; local generated evidence) records every numbered file's hash. `US5CA1CK` was initially chosen for its SECTR1/2 values; examining EXCLIT=4 explained why OpenCPN correctly showed extinguished-light symbols instead of active sectors. The separate Humboldt case tests active lights.

## Findings and changes

1. **Soundings:** replace decimal text with the atlas's compound digits and individual pivots, including the lower fractional digit, drying underline and reliability/swept qualifiers. The detail scene now reproduces the characteristic S-52 number arrangement. Native points do not inherit generic label decluttering; collisions remain possible.
2. **Text:** honour TX/TE format strings, offsets, justification, font weight and colour. At the reference settings typical labels are now 16 px instead of 11 px. GeoServer's label placement/selection still differs visibly: some names shown by OpenCPN are omitted while others appear in GeoServer.
3. **Restrictions and boundaries:** RESTRN without a value no longer invents a warning or boundary. RESARE keeps its own boundary and uses ranked restriction/category symbols. A separate shared-coastline priority fix removes coincident lower-priority area edges. This fixes substantial clutter, but removes more magenta pixels than the reference; complete primitive-edge priority/MASK is still needed.
4. **Lights and wrecks:** add light characteristics, sectors, obscured sectors and orientation; use the pre-oriented raster flare correctly. Add attribute-based point-wreck symbols, depths and Wk labels. Contextual isolated-danger promotion and full compound-light description rules remain incomplete.
5. **Patterns and topmarks:** honour vector pattern definitions even when a bitmap preview exists, apply specified spacing and stagger alternating rows. This reduces the overly dense marsh pattern. Resolve floating versus fixed topmark parents through per-cell co-location. The comparison corpus does not exhaust every topmark shape; unit tests cover representative variants and the parent lookup.

## Image measurements and limits

Fixed exclusions remove the top/bottom 60 px and left/right 20 px for OpenCPN controls, chart borders and scale bars. San Clemente additionally excludes x≥650, which lies outside the ENC and shows OpenCPN's global basemap. A pixel agrees if every RGB channel differs by at most 12. Flat-area pixels are selected from the reference only, with ≤2 channel variation at offsets ±3 px horizontally/vertically. This still includes some symbol interiors and is not a pure polygon-class accuracy metric.

| Scene | Before agreement | Revised agreement | Before RGB MAE | Revised RGB MAE | Revised flat-area agreement |
| --- | ---: | ---: | ---: | ---: | ---: |
| New York day | 75.55% | 76.05% | 14.43 | 15.79 | 95.50% |
| New York detail | 80.92% | 83.91% | 10.10 | 9.58 | 96.87% |
| Dusk | — | 84.64% | — | 3.24 | 97.16% |
| Night | — | 85.12% | — | 3.49 | 97.37% |
| San Clemente | — | 84.10% | — | 8.90 | 98.23% |
| Humboldt Bay | — | 88.96% | — | 7.50 | 98.33% |

The day overview's global MAE **worsened**, despite corrected features and a small increase in threshold agreement. Larger text makes differing label placement more expensive in pixel metrics. Dusk/night percentages also benefit from the palettes' lower contrast. Do not average these into an S-52 compatibility percentage. No original baseline was captured for the last four scenes, so none is claimed.

Day magenta pixel counts changed from 18,185 to 797 against 3,499 in OpenCPN; detail changed from 16,341 to 230 against 2,140. These counts include genuine symbols and boundaries, not just errors. They show that the earlier excess was reduced **and that exact edge equivalence has not been reached**.

Remaining discrepancies: polygon label/symbol anchors, line width/anti-aliasing, incomplete shared-edge priority and spatial-quality handling, pattern origin, light text rounding/compound groups, isolated danger context, and general obstruction portrayal. No IHO S-64 or ECDIS conformance claim is made.

## Reproduction

Build the reference image, start it with the catalogue mounted read-only, run Xvfb `:99` and openbox, and initialise OpenCPN once with the comparison chart and the saved settings. No host desktop, engine socket, privileged mode or host display device is needed. `scripts/reference_capture.py` captures an already-initialised container and records requested/actual configuration; the script does not accept first-run agreements on the user's behalf.

```bash
source scripts/env.sh
python scripts/reference_capture.py --out evidence/portrayal/reference-day --palette day
python scripts/reference_capture.py --out evidence/portrayal/reference-detail --ppm .4
python scripts/reference_capture.py --out evidence/portrayal/reference-dusk --palette dusk
python scripts/reference_capture.py --out evidence/portrayal/reference-night --palette night
# Other cells: --cell, --lon, --lat, --workspace and --chart-dir select the recorded scene.
python scripts/compare_portrayal.py
```

Publish the same cell using `scripts/publish.py` in its separate `reference*` workspace, then fetch the exact URL from each `scene.json` to `after/<scene>.png`. Full screenshots retain UI overlays; the comparison crop and masks are applied only to analysis.

Validation: 22 Java tests and 10 Python tests passed with the real NOAA sample/update chain and national catalogue enabled. The nine-region national WMS check, all three WMTS palettes with repeat cache hits, and WMS 1.1.1/1.3.0 pixel equality passed. Windows-native curl reached the container viewer with HTTP 200. Evidence is in `evidence/portrayal/catalogue-smoke/results.json`.
