# Shared ENC styles

On startup the plugin registers its global day, dusk, and night styles and installs their graphics using GeoServer’s catalogue and resource store. A fresh server can list the full library before it opens a chart. The manifest at `/rest/resource/styles/enc-library-v1/manifest.json` lists per-class defaults, drawing passes, checksums, the library revision, and known portrayal limitations. Each `enc_v1_` style belongs to a particular palette, class, and optionally a drawing priority.

Both catalogue and single-cell publishers use this manifest. Their `--shallow`, `--safety`, and `--deep` settings are persisted as `shallowDepth`, `safetyDepth`, and `deepDepth` in metres. Defaults are 2, 5, and 10. Each feature supplies its store's thresholds, and each cell chooses its own available safety contour. Republishing a workspace with new thresholds updates the store. Refresh cached tiles for every affected chart group.

## Rebuild

From a development checkout with Python and Pillow, run `python scripts/style_library.py`. The inputs are the pinned files under `portrayal/upstream` and the compiler. Commit the generated schema and archive with the compiler change. Maven, the container build, and the source-only offline kit package the same resources. The offline image build uses the bundled archive directly. Published library namespaces are immutable. Ship changed styles under a new library version so existing assignments continue to resolve.

## Existing installations

After upgrade, existing layer and group assignments continue to resolve. Republishing selects the new styles. To preserve an existing file catalogue's group order during bulk migration, take a backup, start a separate copy once to install the new library, then stop that copy. Run `python scripts/migrate_style_library.py COPY --trusted-legacy-data-dir VERIFIED_OLD_INSTALL` to preview replacements. Supply additional trusted directories when style definitions came from multiple installations. The tool compares the SLD contents with independently verified copies. Use `--apply` to write the replacements. Refresh affected tile caches, compare WMS maps and newly rendered WMTS tiles, and stop the copy before running the separate `--cleanup --apply` pass. Review retained styles and graphics in the JSON report. This offline utility operates on GeoServer file catalogues.

## GeoServer Cloud

Build the release-matched plugin into each service that uses the store or portrayal. Cloud 3.0.2 additionally accepts external JARs in `/opt/additional_libs`. Cloud 3.0.0 uses the built-in service classpath. See the [Cloud integration and verification guide](../cloud/README.md). Provide GeoPackage dependencies, native GDAL, and identical mounted chart and cache paths in each process that opens the datastore. Use one catalogue writer (for example the REST service) with `-Denc.installStyles=true` and set `-Denc.installStyles=false` on the remaining services. The writer and renderers must see the same catalogue and style resource store.

## Validation on 2026-11-23

Two builds without chart inputs produced the same archive. Schema version 1 covers 218 chart classes. The manifest identifies 1,530 styles and 1,236 graphics across the three palettes.

| Installation | Observed result |
| --- | --- |
| Standalone GeoServer 2.28.0 and 3.0.2 | Each empty server registered 1,530 ENC styles. Single-cell, maritime catalogue, and inland catalogue publication created zero workspace styles. Concurrent 2/5/10 m and 1/12/25 m requests used the same styles and produced different depth portrayal. WMS and WMTS checks passed after restart. The offline kit also built with networking disabled and installed the full library on a fresh Kartoza 2.28.0 server. |
| GeoServer Cloud 3.0.2, pgconfig | The shared styles appeared in REST and the authenticated Styles page. WFS returned the ENC attributes. Both WMS replicas returned identical images through all three palettes, and GWC served nonblank WMTS tiles for each. Restarting the writer and a renderer preserved the style count and service results. |
| Existing multi-source demo | Nine workspaces retained their 23 chart groups. Cleanup removed 2,628 verified legacy style definitions and 2,063 unused graphics. The final registry contains 1,530 global ENC styles, five GeoServer defaults, and zero workspace-local styles. |

For image comparisons, use identical chart views and tile-cache conditions. During validation a restarted instance of the previous plugin reproduced the NOAA catalogue differences seen against a long-running process. Two reference WMS detail views also varied in the previous plugin depending on whether preceding WMTS requests rendered fresh tiles or served cached ones. Comparing equivalent runs yielded matching reference images and catalogue WMS/WMTS results.
