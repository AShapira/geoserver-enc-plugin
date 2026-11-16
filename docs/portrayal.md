# Portrayal implementation and remaining fidelity gaps

The aim is an S-52-like ENC visualization from S-57 data. The source is a pinned OpenCPN portrayal catalogue, not a manually invented nautical icon set. **The renderer has not passed IHO S-64 tests or a reference-ECDIS comparison.** Visual inspection of NOAA samples is evidence of a working map, not a conformance test.

## Implemented

- Day-bright, dusk and night colour tables and symbol atlases from OpenCPN, with source hashes and license notices.
- Schema-aware lookup selection by object class, geometry primitive and feature attributes; specific matches suppress generic fallback rules. List attributes preserve their ordering; membership rules do not confuse `1` and `11`.
- Simplified point symbols, plain area boundaries and line lookup tables. Bitmap symbols are padded around their source pivot so they remain registered to the feature location.
- Static `AC`, `LS`, `SY`, `AP`, `LC`, and formatted `TX`/`TE` instructions. Text retains formatting, colour, justification, offsets and normalized body size. HPGL pattern and line definitions are rendered to antialiased PNG tiles; pattern spacing and stagger are supported.
- Global display-priority passes in the GeoServer layer group, including separate styles when one object class occupies multiple priorities. Geometry filters prevent point, line and area rules from applying to each other.
- SCAMIN filtering through the normalized ENC scale environment (with the standard WMS scale as fallback). Display-base features remain visible. This is a full-content preset, including soundings; separate standard/base/user-category controls are not yet exposed.
- Fixed shallow/safety/deep metre bands; unknown depth is no-data colour, with the dredged-area fallback/pattern. Select the first available contour at or deeper than the safety setting. Soundings use native S-52 digit pivots, lowered fractional digits, drying marks and swept/unreliable-depth decorations.
- Native coloured flares, sector arcs and legs, directional bearings, obscured sectors, and light-characteristic labels. Raster flares already encode a 135-degree bearing; rotation applies only the difference.
- Ranked RESTRN/RESARE symbols; absent RESTRN creates no restriction graphic. Selected area boundaries yield to coincident COALNE/SLCONS lines. Floating/fixed topmarks use a lazy per-cell co-location index. Point wrecks use depth, category and water level, sounding glyphs and Wk labels.
- Separate palette layer groups for WMTS caching, 4×4 metatiles and a 64-pixel gutter. Requested arbitrary `ENV` settings are not a supported WMTS personalization mechanism.
- Full-catalogue schemas and global style passes, actual `M_COVR` coverage clipping, scale-based cell selection and overlap suppression before class filtering. Each cell supplies its own available safety contour. A GeoServer WMS callback provides rendering scale to the catalogue store, including GWC renders.

Each generated `manifest.json` lists the styles, assets, thresholds, chosen safety contour, object counts and encountered implementation limitations. It includes theoretical rule limitations for the cell's classes, not just symbols visible in one viewport.

## Explicit approximations

| Area | Current limit | Fidelity work |
| --- | --- | --- |
| Depth areas | Fixed four-colour metre preset; unknown depth differs from OpenCPN's intertidal default | Two-shade control and full contour-promotion semantics |
| Soundings | Native glyphs rendered as points; overlapping soundings may collide | Density/thinning policy, non-metre presets and further quality cases |
| Wrecks/obstructions | Point wreck attributes supported; generic obstruction/area treatment remains | Contextual surrounding-depth and isolated-danger promotion |
| Lights | Sector graphics and characteristics supported | Co-located sector radii/flare separation, compound-group formatting, height/range rounding and extended-sector mode |
| Topmarks | Co-location rounded to 1e-7 degree; missing buoy parent defaults fixed | Explicit feature relationship/primitive association for unusual ENC encodings |
| Position quality | Default coastline/construction | Preserve spatial primitives/edge quality and port QUAPOS/QUALIN/SLCONS |
| Patterns and lines | Staggered tiles; precomputed native shared edges, orientation, MASK and visible lookup-priority ownership | Conditional priority promotions, complete spatial-quality styles, pattern phase, complex-line corners and device calibration |
| Labels | Formatted text, 96-dpi OpenCPN default size; different collision and area-anchor algorithms | Text groups, national names, abbreviation, exact text placement and high-DPI corpus |
| Coverage | Catalogue quilting uses a 4× compilation-scale heuristic, deterministic overlap ownership and M_COVR clipping; overview gaps remain where no eligible chart exists | Reference ECDIS chart selection, scale-boundary behavior, dateline and tile-boundary regression corpus |
| Chart metadata | Preserved in cache, not all displayed | Quality overlays, compilation-scale warnings, temporal/seasonal feature controls |

Three symbols referenced by the pinned lookup catalogue are absent from its symbol definitions (`ESSARE01`, `PSSARE01`, `FLTHAZ02`); those rules use the catalogue's question-mark fallback and report it. They are not silently replaced with an unrelated navigation symbol.

The implementation was compared with actual OpenCPN 5.12.4 renders of three identical NOAA cells, across six scenes, and repeated after the November 16 optimizations. See the [latest comparison and resource measurements](optimization-2026-11-16.md), [native metadata contract](edge-metadata.md), and the [historical November 15 comparison](portrayal-comparison.md). Label placement and other contextual portrayal differences remain; pixel agreement is not a conformance score.

## Validation route toward higher fidelity

Build a golden-image corpus from authorized reference renders and the [IHO S-64 test datasets](https://iho.int/standards-and-specifications), recording cell edition/update, display category, palette, safety settings, scale, pixel size and CRS. Compare geometry, symbol presence/selection, colour areas and labels separately. Add conditional procedures one at a time with feature-level fixtures and golden images. Test neighbouring tiles across metatile boundaries and multiple device pixel ratios; the current smoke test demonstrates caching, not complete seam-free label placement. Only after those tests should stronger S-52 compatibility claims be considered.
