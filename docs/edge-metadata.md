# Native edge and lookup metadata

The S-57 store retains immutable GDAL GeoPackage snapshots and adds a separate SQLite sidecar per cell. The sidecar is prepared once, either by the administrative prewarm command or on first use. This replaces the former five-class coastline union/difference approximation; no JTS overlay is needed to discover a cell's shared edges at render time. Coverage quilting and clipping between charts still use geometry overlays.

## Identity and import

The filename is `<snapshot SHA-256>-<portrayal revision>.edges.sqlite`. The snapshot identity already includes the absolute source path, base plus numbered update bytes, GDAL version and conversion recipe. The portrayal revision hashes the sidecar format, lookup/line-ownership recipe and the exact bundled `chartsymbols.xml`. Changing lookup selection or ownership semantics requires a new revision. Old snapshots and sidecars are never silently reinterpreted.

`EdgeCache` invokes GDAL outside the JVM with `UPDATES=APPLY`, `RETURN_LINKAGES=ON`, `RETURN_PRIMITIVES=ON` and `LIST_AS_STRING=ON`. It checks the applied update sequence and verifies the source fingerprint again before publishing. Edge coordinates are reconstructed from the start ConnectedNode, intermediate Edge vertices and end ConnectedNode. An Edge with no intermediate vertices is still a valid two-node segment. [GDAL's S-57 driver documents the omitted endpoint coordinates and primitive/linkage options](https://gdal.org/en/stable/drivers/vector/s57.html).

The importer writes a temporary database, commits, runs SQLite `quick_check`, then atomically renames it. A per-sidecar file lock coordinates server and prewarm processes. Missing nodes, broken edge references, inconsistent linkage arrays or source changes fail the import. The service cannot publish a partial sidecar. The normal image needs no GDAL JNI binding or additional database server.

## Stored contract

| Table | Contents |
| --- | --- |
| `metadata` | Format, portrayal revision and source snapshot identity |
| `edges` | Native RCID, full WKB line, start/end node RCID, QUAPOS and POSACC |
| `features` | Class/RCID, selected lookup RCID, conditional restriction priority, whether the compiled portrayal draws a line, base-category SCAMIN, primitive type and contour/depth inputs |
| `links` | Ordered FSPT edge references with orientation, usage and mask; indexed by edge for ownership |
| `point_quality` | Qualified IsolatedNode/ConnectedNode geometries linked to point features, with QUAPOS/POSACC; individual nodes remain distinct |

Lookup selection follows the compiler's Plain/Lines/Simplified tables, stable specificity ordering, null predicates, numeric comparisons and ordered list matching. `_enc_lookup` allows each SLD rule to use one integer comparison instead of repeating nested attribute/exclusion expressions. The current format is `enc-edges-2`, revision `04fd21ddab6c8e39`. RESTRN values 1–8 or 14 promote only lookups invoking RESARE02 to priority 6. Contour inputs remain in the immutable sidecar; opening a store resolves its fixed `safetyDepth` preset, selects the next available deeper DEPCNT, promotes safety contours to priority 8 and removes their SCAMIN cutoff. Line DEPARE intervals spanning the safety depth are included. `_enc_priority` and `_enc_safety` expose the same decisions to SLD filters and the global layer-group passes. Different safety presets have separate store contexts; no settings-dependent result is written into shared metadata. Existing source attributes and polygon geometry remain available unchanged.

Only features whose compiled portrayal actually draws lines compete for ownership. In particular, filled DEPARE polygons do not own linework; DRGARE polygons do because their portrayal includes an outline. This distinction has a regression test. MASK=1 suppresses an edge; unmasked links retain their native ordering and ORNT=2 reverses direction. The highest visible effective display priority owns a shared edge; equal-priority owners remain eligible. Conditional priorities apply to both ownership and global drawing order. Display-base owners ignore SCAMIN, matching generated styles. Line chains are broken at suppressed or disconnected edges. If a line feature has no native edge links, its source line/polygon boundary remains the explicit fallback.

The original `_enc_line` contains all surviving linework. `_enc_line_normal` and `_enc_line_quality` partition it at native edges: QUAPOS 2–9 is unreliable; missing, 1, 10 and 11 retain normal portrayal. Specific coastline lookups containing a direct LS instruction keep that prescribed stroke, including marsh coastline. Quality changes break chains so reliable and unreliable segments cannot be joined accidentally. Masks, higher-priority ownership and orientation apply before partitioning. Lookups invoking QUAPOS/QUALIN or SLCONS use LOWACC21 on the unreliable geometry; depth contours use dashed DEPCN/DEPSC. SLCONS normal line widths/dashes follow CONDTN, CATSLC and WATLEV; conspicuous COALNE retains its CHMGF under-stroke.

`_enc_quapos` joins a point feature back to its qualified spatial primitive by feature identity and coordinate. This also supports GDAL-expanded SOUNDG points without applying one node’s quality to the whole feature. QUAPOS point symbols and sounding/wreck depth qualifiers use this value. POSACC is retained quantitatively; it is not converted into an invented accuracy radius.

Each retained cell caches the three assembled line geometries by feature and effective SCAMIN band in an estimated-byte LRU capped at 4 MiB. This avoids a separate entry for every tiny scale change while preserving the inclusive visibility threshold. Uniform-quality chains share geometry objects, and quilt clipping reuses identical geometry within a feature. Unscaled requests have a distinct cache band because every owner is eligible. Source-dependent no-link fallbacks are not cached under RCID alone. Raw topology, point-coordinate indexes and lookup maps are retained with the cell store; the LRU limit is not a bound on their size. Catalogue cell stores retain the existing target of 32 leases, with active readers allowed to exceed it temporarily. Native BBOX predicates are pushed to GeoPackage before enrichment; the complete query filter is evaluated afterward, including virtual attributes.

## Boundaries of the implementation

Ownership follows the conditional procedures implemented by this compiler, including RESARE and safety contours. Surrounding-depth isolated-danger promotion, complete WRECKS/OBSTRN area procedures, quality viewing-group switches, all modern Presentation Library procedures and chart-to-chart shared topology remain incomplete. USAG is retained; it does not independently override edge ownership. Labels, pattern phase, line joins and device calibration still differ from OpenCPN. See the November 17 report for deliberate differences from OpenCPN’s legacy quality symbols and disabled safety-priority promotion. No S-52 conformance is claimed.

## Operations

```bash
# Run from the checkout or extracted kit.
container/operator.sh java -Xmx2g -cp '/opt/enc/s57/gs-s57.jar:/usr/local/tomcat/webapps/geoserver/WEB-INF/lib/*' \
  org.enc.geoserver.EdgeCache /opt/enc-data/catalogue.sqlite /opt/enc-cache /usr/bin/ogr2ogr 4
container/operator.sh python3 /opt/enc/scripts/audit_edges.py --catalogue /opt/enc-data/catalogue.sqlite \
  --cache /opt/enc-cache --out /opt/enc-cache/edge-audit.json
```

The audit checks every expected cell fingerprint, revision, SQLite integrity and edge/feature and point-quality foreign-key relationships, then reports counts and unmatched lookups. Rerunning prewarm reuses already published sidecars. Publish matching styles and invalidate generated tiles whenever the portrayal revision changes. The demo script performs prewarm and then seeds its bounded WMTS plan. No global image/cache pruning is performed.

The tuning helper persists `gwc/geowebcache-diskquota.xml` through the authenticated resource API and reloads this dedicated GeoServer instance. This is necessary for GWC 2.0.2, whose quota PUT does not save the changed bean. `--quota-resource` supports a different data-directory-relative GWC configuration location. Verify quota state after restart as well as immediately after applying it.
