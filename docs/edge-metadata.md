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
| `features` | Class/RCID, selected lookup RCID, display priority, whether the compiled portrayal draws a line, effective SCAMIN and primitive type |
| `links` | Ordered FSPT edge references with orientation, usage and mask; indexed by edge for ownership |

Lookup selection follows the compiler's Plain/Lines/Simplified tables, stable specificity ordering, null predicates, numeric comparisons and ordered list matching. `_enc_lookup` allows each SLD rule to use one integer comparison instead of repeating nested attribute/exclusion expressions. SCAMIN and conditional portrayal filters still run at render time. Existing source attributes and polygon geometry remain available unchanged.

Only features whose compiled portrayal actually draws lines compete for ownership. In particular, filled DEPARE polygons do not own linework; DRGARE polygons do because their portrayal includes an outline. This distinction has a regression test. MASK=1 suppresses an edge; unmasked links retain their native ordering and ORNT=2 reverses direction. The highest visible display priority owns a shared edge; equal-priority owners remain eligible. Display-base owners ignore SCAMIN, matching generated styles. Line chains are broken at suppressed or disconnected edges. If a line feature has no native edge links, its source line/polygon boundary remains the explicit fallback.

Each retained cell caches assembled line geometries by feature and effective SCAMIN band in an estimated-byte LRU capped at 4 MiB. This avoids a separate entry for every tiny scale change while preserving the inclusive visibility threshold. Raw topology and lookup maps are retained with the cell store; the LRU limit is not a bound on their size. Catalogue cell stores retain the existing target of 32 leases, with active readers allowed to exceed it temporarily. Native BBOX predicates are pushed to GeoPackage before enrichment; the complete query filter is evaluated afterward, including virtual attributes.

## Boundaries of the implementation

Ownership follows the priorities implemented by this portrayal compiler. Conditional ECDIS priority changes, complete spatial-quality line styles, all isolated-danger procedures and chart-to-chart shared topology are not implemented. QUAPOS/POSACC and USAG are retained for further portrayal work; retaining them does not mean that every qualifier is rendered. Labels, pattern phase and complex-line placement can still differ from OpenCPN.

## Operations

```bash
# Inside the deployed container; four independent GDAL worker processes.
java -Xmx2g -cp '/usr/local/tomcat/webapps/geoserver/WEB-INF/lib/*' \
  org.enc.geoserver.EdgeCache /opt/enc-data/catalogue.sqlite /opt/enc-cache /usr/bin/ogr2ogr 4
python3 /opt/enc/scripts/audit_edges.py --catalogue /opt/enc-data/catalogue.sqlite \
  --cache /opt/enc-cache --out /tmp/edge-audit.json
```

The audit checks every expected cell fingerprint, revision, SQLite integrity and both link foreign-key relationships, then reports counts and unmatched lookups. Rerunning prewarm reuses already published sidecars. Publish matching styles and invalidate generated tiles whenever the portrayal revision changes. The demo script performs prewarm and then seeds its bounded WMTS plan. No global image/cache pruning is performed.

The tuning helper persists `gwc/geowebcache-diskquota.xml` through the authenticated resource API and reloads this dedicated GeoServer instance. This is necessary for GWC 2.0.2, whose quota PUT does not save the changed bean. `--quota-resource` supports a different data-directory-relative GWC configuration location. Verify quota state after restart as well as immediately after applying it.
