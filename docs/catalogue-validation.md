# National catalogue container validation — 2026-11-15

This extends the [2026-11-13 single-cell checks](validation.md). The running service is a detached rootless Podman container, built from the official vanilla `docker.osgeo.org/geoserver:3.0.2` image. It has the S-57 plugin added to `WEB-INF/lib`, without replacing GeoServer/GeoTools libraries. No unrelated service was changed.

## Runtime and inventory

| Item | Executed configuration |
| --- | --- |
| GeoServer / GeoTools | 3.0.2 / 35.2 |
| Official base image | `docker.osgeo.org/geoserver:3.0.2` |
| Base image repository digest | `sha256:2da4103f1071a7b9e470dde5e547b851b1b3fa0d492427e803979cb2eaf0ccca` |
| Container GDAL | 3.8.4, S57 and GPKG drivers |
| Container Java / servlet runtime | JDK 21 / Tomcat 11 |
| Container engine | Rootless Podman 5.8.2 in RHEL WSL2 |
| Source catalogue | NOAA `ENCProdCat.xml`, valid 2026-11-14T05:58:23Z |
| Source exchange archive | NOAA `All_ENCs.zip`, approximately 779 MB |
| Active / excluded cancelled cells | 7,114 / 166 |
| Indexed cells / failures | 7,114 / 0 |
| Source features | 6,965,828, including metadata and association records |
| Serving store | One `noaa:chart` catalogue store, shared by all regions and palettes |
| Publication | 137 portrayed classes, 168 ordered style passes, 211 assets per palette |
| Named-volume disk use | Approximately 2.2 GB source/index, 11 GB cache, 46 MB GeoServer state before additional tiles |

The full [inventory report](noaa-catalogue-report.json) records both input SHA-256 hashes, class counts, coverage repairs and failures. Index preparation used GDAL 3.11.5 on the development host. Every cell was subsequently converted/read with GDAL 3.8.4 in the actual container. The initial parallel cache warm completed in 139.7 seconds, converting 7,103 cells after 11 had already been imported by rendering requests. A subsequent [warm report](noaa-warm-report.json) records reuse of all 7,114 snapshots.

An independent read-only pass checked **every one of the 7,114 container snapshots**: the expected cache fingerprint exists, DSID edition/update matches the catalogue, and SQLite `quick_check` returns `ok`. It completed in 130.26 seconds with no failures; see the [integrity report](noaa-integrity-report.json). This validates storage/import consistency, not cartographic conformance.

## Executed checks

- **14 Java tests passed, zero skipped**, including real NOAA base/update ingestion and complete-catalogue discovery/query tests. Added coverage tests verify scale rejection, stable overlap ownership, suppression across classes, callback cleanup, and equivalent axis-order scale calculation under GeoServer's `forceXY` setting.
- **7 Python portrayal tests passed**, retaining the original lookup, depth, pattern/symbol, palette and depth-unit regressions.
- Live chart renders cover New York, San Francisco, Chesapeake Bay, Chicago, Seattle, Anchorage, Honolulu, Guam and the continental overview. Exact BBOXes, timings and WMTS requests are recorded in [machine-readable results](catalogue-validation.json).
- All three palette WMTS requests return PNG tiles; their repeated requests are byte-identical cache hits. Equivalent WMS 1.1.1 and WMS 1.3.0 EPSG:4326 requests are checked pixel by pixel.
- Headless Chromium opens the bundled viewer, loads New York WMTS, switches to San Francisco, switches to WMS and night mode, and loads the national overview. No JavaScript or HTTP errors occurred. This is Linux browser automation; Windows access is tested independently with native Windows HTTP requests.
- Windows-native `curl.exe` reaches the viewer, WMS PNG and WMTS PNG through the published IPv4 localhost port, including after restarting the server. The old host Java listener was not reachable from Windows; container port publication resolves this without a firewall or port-proxy change.
- Container recreation retains the three named volumes and restarts the persisted service. An immediate `podman restart` encountered a transient pasta port-release race (`Address already in use`); a subsequent `podman start geoserver-enc` succeeded after the old listener exited. The published catalogue and caches persisted, and post-start Windows/browser checks passed. The final container has a health check and `unless-stopped` policy. This does not establish unattended startup after a Windows/WSL reboot.

Two live regressions were found during this work: missing scale propagation selected 5,303 cells for a continental request; north/east WMS axis handling selected a different detail level for equivalent requests. The callback and axis-normalization fixes are logged in [decisions 27 and 30](decisions.md).

## Reproduce

```bash
container/demo.sh
container/operator.sh python3 /opt/enc/scripts/catalogue_smoke.py \
  --url http://127.0.0.1:8080/geoserver --out /opt/enc-cache/enc-smoke
```

For native Java tests, use `S57_TEST_FILE` for the US5NY1AI base plus update, `S57_CATALOGUE` for the prepared inventory, and `OGR2OGR` for the tested executable. Without these data settings the corresponding integration tests are skipped. PNG evidence, browser screenshots and execution logs remain under local `evidence/catalogue/` and `.runtime/`.

## Limits

All active cells were indexed, imported and integrity-checked; representative regions were rendered, rather than manually inspecting every chart. The scale cutoff can leave gaps at very small scales where NOAA has no eligible overview cell. Dateline edge cases, every scale transition, full tile-seam behavior and high-load service capacity are not established by these checks. The regional timings are smoke-test observations on this machine, not a capacity benchmark.

Portrayal remains experimental: full S-52 conditional procedures, reference-ECDIS comparison and S-64 acceptance remain outstanding. See [portrayal gaps](portrayal.md). This is a recorded NOAA snapshot, with no automatic refresh; it is not a claim that the charts remain current after the download.
