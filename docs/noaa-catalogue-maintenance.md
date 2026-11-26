# Maintain the original NOAA catalogue installation

Prepared by Codex.

Use this procedure for the original NOAA demo with a product XML, an inventory at `/opt/enc-data/catalogue.sqlite` (or a versioned path under that volume) and the three named volumes below. For a workspace installed by `enc deploy`, use the [exchange-directory publishing guide](publishing-guide.md). Inspect the actual container mounts before using any volume name from this example.

This guide follows the official vanilla GeoServer container deployment in this
repository. It covers the full NOAA catalogue, with one store and object-class
layers shared by three S-52-derived chart groups. It does not create a store for
each `.000` file. Portrayal remains experimental; see [coverage and limitations](portrayal.md).

Run the Bash commands on the host, from the repository root. Commands inside
`podman run` or `podman exec` run in a container; `/opt/...` paths are container
paths. Python, GDAL, Pillow and Java come from the image. The examples use the
dedicated local demo, its three named volumes and its default depth thresholds.
For the full service on a disconnected site, use the [air-gap deployment guide](airgap-deployment.md). The [Kartoza guide](kartoza-2.28.0.md) and [plugin build manual](../airgap/README.md) cover other image layouts.

For a **first installation**, the automated equivalent is:

```bash
container/demo.sh
```

The manual steps below explain and reproduce the stages. Choose the automated
or manual first installation; do not run both as consecutive setup steps.
For an existing installation, go to [Updating an existing catalogue](#8-updating-an-existing-catalogue).
The launcher reuses its original inventory; it does not download NOAA updates.

## 1. Set up the working shell and image

Use the same Bash session for the following steps. Stop if any command fails.
These settings are also used by the update procedure:

```bash
set -euo pipefail
export ENC_ENGINE=podman
export CONTAINER_ENGINE=$ENC_ENGINE
export ENC_CONTAINER=geoserver-enc
export ENC_IMAGE=localhost/enc-operator:3.0.2
export GEOSERVER_USER=admin
export GEOSERVER_PASSWORD=geoserver  # Default only for this local demo.
export ENC_CATALOGUE_VOLUME=geoserver-enc-catalogue
export ENC_CACHE_VOLUME=geoserver-enc-cache
export ENC_CONFIG_VOLUME=geoserver-enc-data
export ENC_SHALLOW=2 ENC_SAFETY=5 ENC_DEEP=10
export ENC_INDEX=/opt/enc-data/catalogue.sqlite
export ENC_RUN="initial-$(date -u +%Y%m%dT%H%M%SZ)"
export ENC_REPORT="/opt/enc-cache/reports/$ENC_RUN"
```

For a server with changed credentials, replace the password assignment with
`read -rsp 'GeoServer password: ' GEOSERVER_PASSWORD; export GEOSERVER_PASSWORD`.
The password is passed through the environment, not a publisher command-line
argument. The examples assume the plugin owns the `noaa` workspace.

For a fresh manual installation create the stock server and its persistent volumes with `container/demo.sh --empty`. The full automated download and publication workflow is `container/demo.sh`. The following manual steps operate on the same volumes using the operator image.

| Volume | Container path | Purpose and server access |
| --- | --- | --- |
| `geoserver-enc-catalogue` | `/opt/enc-data` | NOAA downloads, immutable exchange sets, inventory; read-only in GeoServer |
| `geoserver-enc-cache` | `/opt/enc-cache` | Converted GeoPackages, edge metadata and operation reports; writable |
| `geoserver-enc-data` | `/opt/geoserver_data` | GeoServer configuration, installed styles/symbols and default GWC tile storage; writable |

Keep the cache writable even after precomputation: imports use lock files and
may create new snapshots. The tile quota does not limit source files, GeoPackages
or edge sidecars. See the [measured disk use](portrayal-2026-11-17.md); allow room
for both old and new generations during an update.

## 2. Download NOAA data and prepare `catalogue.sqlite`

Define this helper once. It downloads the XML inventory and complete exchange
archive, then prepares an inventory in the directory containing `ENC_INDEX`.
For an update, that directory must be new; `mkdir` refuses to reuse it.

```bash
prepare_catalogue() {
  "$ENC_ENGINE" run --rm --memory 6g --cpus 4 \
    --volume "$ENC_CATALOGUE_VOLUME:/opt/enc-data" \
    -e "ENC_INDEX=$ENC_INDEX" \
    --entrypoint /bin/bash "$ENC_IMAGE" -ceu '
      enc_out=$(dirname "$ENC_INDEX")
      if [[ "$enc_out" == /opt/enc-data ]]; then
        test ! -e "$ENC_INDEX"
      else
        [[ "$enc_out" == /opt/enc-data/generations/* ]]
        mkdir -p /opt/enc-data/generations
        mkdir "$enc_out"
      fi
      mkdir -p "$enc_out/downloads"
      curl -fL --retry 3 https://charts.noaa.gov/ENCs/ENCProdCat.xml \
        -o "$enc_out/downloads/ENCProdCat.xml"
      curl -fL --retry 3 https://charts.noaa.gov/ENCs/All_ENCs.zip \
        -o "$enc_out/downloads/All_ENCs.zip"
      python3 /opt/enc/scripts/catalogue.py \
        --catalogue "$enc_out/downloads/ENCProdCat.xml" \
        --archive "$enc_out/downloads/All_ENCs.zip" \
        --out "$enc_out" --workers 4
    '
}
```

For the first manual installation, run:

```bash
prepare_catalogue
```

[`catalogue.py`](../scripts/catalogue.py) performs these steps:

1. Hash the archive and extract it under `exchanges/<archive-sha256-prefix>/`.
   Retain each `.000` base with all adjacent numbered updates (`.001`, `.002`,
   etc.). GDAL opens the base with `UPDATES=APPLY`.
2. Select every active cell listed in the XML. Reject missing cells, mismatched
   editions/applied update numbers, native read failures and incompatible field
   types. Cancelled cells are excluded.
3. Derive actual coverage from `M_COVR`: include coverage polygons, subtract
   exclusions, and record geometry repairs. Read compilation scale, usage band,
   available depth contours, class counts and the union of attribute schemas.
4. Write `catalogue.sqlite.partial`, then rename it to `catalogue.sqlite` only
   after successful preparation. Write hashes, counts and failures to
   `catalogue-report.json`. Early download/extraction failures can occur before
   that report exists.

The SQLite file is a **plugin inventory**, not a GeoPackage containing all chart
features and not GeoServer's own configuration catalogue:

| Table | Contents |
| --- | --- |
| `metadata` | Inventory format, source archive hash, creation time and active-cell count |
| `cells` | Cell name, relative source path, edition/update, scale/band, coverage WKB and contour values |
| `cell_classes` | Feature counts for each cell/object class |
| `fields` | Unified field names, types and order for each object class |

Paths in `cells` are relative to the inventory's parent directory. Keep the
inventory and its `exchanges/` directory together. Moving just the SQLite file
breaks those references. Detailed features are converted separately into cached
GeoPackages.

## 3. Start GeoServer with the plugin

The launcher in step 1 has already started the server with the plugin ZIP mounted. Confirm readiness with `container/operator.sh curl -fsS 'http://127.0.0.1:8080/geoserver/ows?service=WMS&request=GetCapabilities'`.

## 4. Precompute GeoPackages and shared-edge metadata

Define the helper below, then run it. It uses the matching operator image and the same absolute source
paths as GeoServer so the cache fingerprints match. Preparation can run while
the existing catalogue continues serving; it consumes additional CPU, RAM and
disk. Reduce worker counts/resource limits if necessary.

```bash
prewarm_catalogue() {
  container/operator.sh /bin/bash -ceu '
      set -o pipefail
      mkdir -p "$ENC_REPORT"
      python3 /opt/enc/scripts/warm_catalogue.py \
        --catalogue "$ENC_INDEX" --cache /opt/enc-cache \
        --ogr2ogr /usr/bin/ogr2ogr --workers 4
      cp /opt/enc-cache/warm-report.json "$ENC_REPORT/warm-report.json"
      java -Xmx2g -cp "/opt/enc/s57/gs-s57.jar:/usr/local/tomcat/webapps/geoserver/WEB-INF/lib/*" \
        org.enc.geoserver.EdgeCache "$ENC_INDEX" /opt/enc-cache /usr/bin/ogr2ogr 4 \
        | tee "$ENC_REPORT/edge-build.log"
      python3 /opt/enc/scripts/audit_edges.py \
        --catalogue "$ENC_INDEX" --cache /opt/enc-cache \
        --ogr2ogr /usr/bin/ogr2ogr --out "$ENC_REPORT/edge-audit.json"
    '
}
```

For the first manual installation, run:

```bash
prewarm_catalogue
```

The GeoPackage stage applies updates, creates spatial indexes and validates new
imports against the inventory. The Java stage precomputes native edges, ordered
feature links, lookup selection and spatial-quality inputs. The audit checks
the expected sidecars, their revision, SQLite integrity and link associations;
review its unmatched-lookup counts as well as errors. A successful audit is not
S-52 conformance testing. See [the metadata contract](edge-metadata.md).

Cache identities include the canonical source path, base/update bytes, GDAL
version and conversion recipe; sidecars also include the portrayal revision.
Do not prewarm through a different mount path and expect GeoServer to reuse the
results. A new archive/generation path can require reconverting unchanged cells
as well, so budget for a complete additional cache generation.

## 5. Publish the store, styles, layers and layer groups

Define this helper. It publishes all three presets using the current `ENC_INDEX`
and keeps generated manifests, SLDs and publication URLs in the reports volume.

```bash
publish_catalogue() {
  for enc_palette in day dusk night; do
    container/operator.sh \
      python3 /opt/enc/scripts/publish.py \
      --catalogue "$ENC_INDEX" --url http://127.0.0.1:8080/geoserver \
      --workspace noaa --data-dir /opt/geoserver_data \
      --cache /opt/enc-cache --ogr2ogr /usr/bin/ogr2ogr \
      --styles "$ENC_REPORT/portrayal-$enc_palette" --palette "$enc_palette" \
      --shallow "$ENC_SHALLOW" --safety "$ENC_SAFETY" --deep "$ENC_DEEP" --update
  done
}
```

For the first manual installation, run:

```bash
publish_catalogue
```

`--update` permits changes to the plugin-owned workspace and invalidates its
chart-group tiles. It also works when the workspace is initially absent. Without
it, the publisher refuses to modify an existing workspace. It does **not** fetch
new NOAA data.

Each [`publish.py`](../scripts/publish.py) invocation performs the following
sequence through GeoServer REST and local filesystem access:

1. **Workspace and store.** Create `noaa` if needed; create or update the store
   `chart`, of type **S-57 ENC (GDAL)**. Set `dbtype=s57`, `catalogue=$ENC_INDEX`,
   `cache=/opt/enc-cache`, `ogr2ogr=/usr/bin/ogr2ogr`, `cellPoolSize=32`,
   `timeout=300` and `safetyDepth=$ENC_SAFETY`. The alternative single-cell `file`
   parameter is omitted. Query available feature types to force the store open.
2. **Portrayal generation.** Compile the pinned S-52 lookup/symbol resources
   against the catalogue's unified class schemas. Generate one combined default
   style per class, separate display-priority styles, PNG symbols/patterns and
   `manifest.json`. Thresholds are in metres; the selected safety contour is the
   first available contour at or deeper than the safety setting in each cell.
   The store's `safetyDepth` and the generated styles must agree.
3. **Style installation.** Copy PNG assets into
   `/opt/geoserver_data/workspaces/noaa/styles/symbols/`, then POST new or PUT
   existing workspace SLD styles through REST. Uploading the SLD alone would
   leave its external graphics missing.
4. **Layer publication.** Publish a feature type and layer for each class with
   supported portrayal, such as `noaa:DEPARE`, `noaa:DEPCNT` and `noaa:SOUNDG`.
   Each class aggregates eligible cells across the catalogue. Set EPSG:4326,
   the catalogue bounds and the class's palette-specific default style.
   Metadata-only classes and classes without supported lookups are not chart
   layers; the inventory still records their source counts.
5. **Layer-group publication.** Create or update a `SINGLE` group named
   `chart_day`, `chart_dusk` or `chart_night`. Its layer/style pairs follow the
   manifest's global display-priority order. A class can appear several times
   with different priority styles; for example, ordinary and safety contours
   use separate passes. Do not deduplicate the list or sort it alphabetically.
6. **Tile configuration.** Configure the group's GeoWebCache layer with 4×4
   metatiles and a 64-pixel gutter. With `--update`, queue PNG truncation jobs for
   both `EPSG:900913` and `EPSG:4326`, zooms 0–22. These jobs are asynchronous.

The three groups have explicit styles for every entry. Publishing night last
changes individual layers' default styles to night, but **does not change the
day or dusk group's appearance**. Use the groups for the complete chart.

The resulting publication is:

```text
NOAA XML + exchange archive
  -> catalogue.sqlite + immutable raw cells
  -> noaa / chart store -> object-class layers
                           + generated SLDs and PNG assets
                           -> ordered chart_day / chart_dusk / chart_night
                           -> WMS and GeoWebCache WMTS

Raw cells -> indexed GeoPackage cache + shared-edge sidecars -> store reads
```

## 6. Wait for invalidation, configure the tile cache and seed

Define this helper and run it **after publication and before seeding**. Waiting
prevents an unfinished truncation job from deleting newly seeded tiles. It
waits for jobs on these three groups, checks reported failures and times out
without cancelling jobs.

```bash
wait_for_chart_jobs() {
  container/operator.sh python3 - <<'PY'
import json, os, sys, time
sys.path.insert(0, "/opt/enc/scripts")
from publish import Server
s = Server("http://127.0.0.1:8080/geoserver",
           os.environ["GEOSERVER_USER"], os.environ["GEOSERVER_PASSWORD"])
deadline = time.monotonic() + 1800
while True:
    pending = {}
    for palette in ("day", "dusk", "night"):
        path = f"/gwc/rest/seed/noaa:chart_{palette}.json"
        tasks = json.loads(s.request("GET", path))["long-array-array"]
        if any(len(task) > 4 and task[4] in (-1, 3) for task in tasks):
            raise RuntimeError(f"Failed or aborted job: {palette}: {tasks}")
        if tasks:
            pending[palette] = tasks
    if not pending:
        print("All chart tile jobs finished")
        break
    if time.monotonic() > deadline:
        raise TimeoutError(f"Inspect pending jobs before continuing: {pending}")
    time.sleep(2)
PY
}
```

After the first publication, run:

```bash
wait_for_chart_jobs
```

Configure the dedicated demo and seed its bounded New York/San Francisco plan:

```bash
container/operator.sh \
  python3 /opt/enc/scripts/tune_cache.py \
  --url http://127.0.0.1:8080/geoserver --apply --seed \
  --quota-gib 2 --regions new-york san-francisco --palettes day dusk night \
  --min-zoom 11 --max-zoom 13 --max-tiles 2048 \
  --report "$ENC_REPORT/tuning-report.json"
```

The script persists a global 2 GiB LRU tile quota, reloads GeoServer to activate
it, adjusts logging/WMS limits and sets group tile expirations. It therefore
affects the dedicated server, not just this catalogue. Seeding waits for its
jobs to finish. Omit both `--apply` and `--seed` to inspect the plan without
changing the server. The bounded seed does not render the whole NOAA catalogue;
other regions/zooms render on demand. Server tiles expire after a week and
client tiles after an hour; explicit truncation handles earlier data changes.

## 7. Verify the publication

Run the regional WMS, axis-order and all-palette WMTS smoke checks and retain
their PNGs and JSON results:

```bash
container/operator.sh python3 /opt/enc/scripts/catalogue_smoke.py \
  --url http://127.0.0.1:8080/geoserver --out "$ENC_REPORT/smoke"

container/operator.sh python3 - <<'PY'
import json, os, sys
sys.path.insert(0, "/opt/enc/scripts")
from publish import Server
s = Server("http://127.0.0.1:8080/geoserver",
           os.environ["GEOSERVER_USER"], os.environ["GEOSERVER_PASSWORD"])
body = json.loads(s.request("GET", "/rest/workspaces/noaa/datastores/chart.json"))
params = {e["@key"]: e["$"] for e in body["dataStore"]["connectionParameters"]["entry"]}
assert params["catalogue"] == os.environ["ENC_INDEX"], params["catalogue"]
print("Published catalogue:", params["catalogue"])
PY
```

The read-back asserts that the store's `catalogue` parameter equals `ENC_INDEX`.
Inspect `catalogue-report.json` alongside the index, and `warm-report.json`,
`edge-audit.json`, `portrayal-*/manifest.json`, `portrayal-*/publication.json`,
`tuning-report.json` and `smoke/results.json` under `ENC_REPORT`. Cell and style
counts depend on the NOAA snapshot and compiler revision; do not hardcode the
historical 7,114-cell count as an acceptance test.

Open [GeoServer](http://localhost:18080/geoserver/web/) and the
[viewer](http://localhost:18080/geoserver/enc/viewer/index.html). In GeoServer, inspect **Stores → chart**,
**Styles**, **Layers**, **Layer Groups → chart_day/dusk/night** and
**Tile Caching → Tile Layers**. The public service endpoints are:

- WMS: `http://localhost:18080/geoserver/wms`, requesting `noaa:chart_day`,
  `noaa:chart_dusk` or `noaa:chart_night` with an empty `STYLES` parameter.
- WMTS capabilities:
  `http://localhost:18080/geoserver/gwc/service/wmts?SERVICE=WMTS&REQUEST=GetCapabilities`.
  Use the same group identifiers and advertised grid-set/matrix identifiers.

## 8. Updating an existing catalogue

This procedure preserves the current source/index and prepares a new generation
before changing the existing `noaa:chart` store. Run one update at a time. The
final REST publication is **not atomic across all styles and palettes**; use a
maintenance window for the switch. See below for a separate-workspace option.

### A. Record the current publication

In a new shell, run the **settings block only** from step 1 and define the four
functions from steps 2, 4, 5 and 6; do not run their example invocations or the
fresh-install build/start commands. Retain your deployed depth thresholds and
credentials. The commands below assume the documented 2/5/10 metre preset.

For an existing deployment, read its active **named volumes** into the current shell before calling any helper. This picks up replacement volumes used by a rehearsed installation. A bind-mounted installation needs its corresponding host paths in the helper commands.

```bash
enc_volume_at() {
  "$ENC_ENGINE" inspect --format '{{json .Mounts}}' "$ENC_CONTAINER" |
    python3 -c 'import json, sys
matches = [m["Name"] for m in json.load(sys.stdin)
           if m["Destination"] == sys.argv[1] and m["Type"] == "volume"]
if len(matches) != 1:
    sys.exit("Expected a named volume for " + sys.argv[1])
print(matches[0])' "$1"
}
ENC_CATALOGUE_VOLUME=$(enc_volume_at /opt/enc-data)
ENC_CACHE_VOLUME=$(enc_volume_at /opt/enc-cache)
ENC_CONFIG_VOLUME=$(enc_volume_at /opt/geoserver_data)
```

Use the existing server's matching operator image, choose a unique generation name and save
the current store and group configuration. The old index path is read from the
live store, not assumed to be the original default:

```bash
ENC_IMAGE=$("$ENC_ENGINE" inspect --format '{{index .Config.Labels "org.enc.operator"}}'  "$ENC_CONTAINER")
export ENC_IMAGE
export ENC_RUN="noaa-$(date -u +%Y%m%dT%H%M%SZ)"
export ENC_REPORT="/opt/enc-cache/reports/$ENC_RUN"
export ENC_INDEX="/opt/enc-data/generations/$ENC_RUN/catalogue.sqlite"

wait_for_chart_jobs
container/operator.sh python3 - <<'PY'
import json, os, sys
from pathlib import Path
sys.path.insert(0, "/opt/enc/scripts")
from publish import Server
s = Server("http://127.0.0.1:8080/geoserver",
           os.environ["GEOSERVER_USER"], os.environ["GEOSERVER_PASSWORD"])
out = Path(os.environ["ENC_REPORT"])
out.mkdir(parents=True, exist_ok=False)
body = s.request("GET", "/rest/workspaces/noaa/datastores/chart.json")
params = {e["@key"]: e["$"] for e in
          json.loads(body)["dataStore"]["connectionParameters"]["entry"]}
old_index = Path(params["catalogue"])
assert old_index.is_file(), old_index
assert float(params["safetyDepth"]) == float(os.environ["ENC_SAFETY"]), "Use the deployed safety preset"
(out / "before-store.json").write_bytes(body)
(out / "previous-catalogue.txt").write_text(str(old_index) + "\n")
for palette in ("day", "dusk", "night"):
    body = s.request("GET", f"/rest/workspaces/noaa/layergroups/chart_{palette}.json")
    (out / f"before-chart_{palette}.json").write_bytes(body)
print("Previous catalogue:", old_index)
PY
ENC_PREVIOUS_INDEX=$("$ENC_ENGINE" exec "$ENC_CONTAINER" \
  cat "$ENC_REPORT/previous-catalogue.txt")
export ENC_PREVIOUS_INDEX
```

These JSON files document the previous publication; they are not a full backup
of GeoServer security, configuration or binary assets. The rollback below uses
the retained sources and the same image/preset to regenerate the publication.

### B. Prepare and validate the new generation

```bash
prepare_catalogue
prewarm_catalogue
```

The new layout is:

```text
/opt/enc-data/generations/noaa-<UTC timestamp>/
  downloads/ENCProdCat.xml
  downloads/All_ENCs.zip
  exchanges/<archive hash>/ENC_ROOT/<cell>/<cell>.000  (+ numbered updates)
  catalogue.sqlite
  catalogue-report.json
```

Check the preparation and audit reports before proceeding. If NOAA changes the
XML/archive between downloads and editions/updates do not match, preparation
fails. Download a fresh pair into a **new generation** and try again; do not
bypass the mismatch check or overwrite the currently served source files.
The old catalogue remains selected until the next step.

### C. Switch the existing publication, invalidate and verify

During the maintenance window, run:

```bash
publish_catalogue
wait_for_chart_jobs
container/operator.sh \
  python3 /opt/enc/scripts/tune_cache.py \
  --url http://127.0.0.1:8080/geoserver --apply --seed \
  --report "$ENC_REPORT/tuning-report.json"
container/operator.sh python3 /opt/enc/scripts/catalogue_smoke.py \
  --url http://127.0.0.1:8080/geoserver --out "$ENC_REPORT/smoke"
"$ENC_ENGINE" exec "$ENC_CONTAINER" /bin/bash -ceu \
  'printf "%s\n" "$1" > "$2/published-catalogue.txt"' \
  -- "$ENC_INDEX" "$ENC_REPORT"
```

Repeat the store read-back and visual checks in step 7. Hard-refresh the viewer
or clear its cached tiles after the switch: server-side truncation cannot evict
tiles already cached by a client. If custom tile formats, grids or zooms outside
the publisher's PNG/two-grid/0–22 scope were added, invalidate those separately.

Updating the store reopens its catalogue snapshot. Republishing **every palette**
updates the groups and their caches consistently. Removed/cancelled cells are
absent from the new inventory. The publisher adds newly supported class layers,
but does not delete old layer registrations or obsolete styles when a class
disappears entirely. New groups contain only their new manifest's entries;
review standalone layers for any required retirement after validation.

For an ordinary restart, use:

```bash
"$ENC_ENGINE" stop "$ENC_CONTAINER"
"$ENC_ENGINE" start "$ENC_CONTAINER"
```

A stop/start preserves the selected inventory. The current demo launcher also retains the active named volumes on recreation and skips initial NOAA publication once the source registry contains NOAA. A manually published legacy workspace may lack that registry entry. For that layout, use the stop/start commands above and keep the recorded store path for rollback.

### D. Roll back if validation fails

Keep the original source/index, old caches and the recorded previous index path.
In the same shell, switch back and republish all presets:

```bash
wait_for_chart_jobs
export ENC_INDEX="$ENC_PREVIOUS_INDEX"
export ENC_REPORT="${ENC_REPORT}-rollback-$(date -u +%Y%m%dT%H%M%SZ)"
publish_catalogue
wait_for_chart_jobs
container/operator.sh \
  python3 /opt/enc/scripts/tune_cache.py \
  --url http://127.0.0.1:8080/geoserver --apply --seed \
  --report "$ENC_REPORT/tuning-report.json"
container/operator.sh python3 /opt/enc/scripts/catalogue_smoke.py \
  --url http://127.0.0.1:8080/geoserver --out "$ENC_REPORT/smoke"
```

If returning in a new shell, recover `ENC_PREVIOUS_INDEX` from that update's
`previous-catalogue.txt` first. A failed/interrupted publication may have changed
only some resources; rerun all palettes against the intended index or perform
this rollback. Failed/timed-out tile jobs need investigation before continuing.
Rollback does not automatically delete extra layer/style registrations created
during the attempted update.

### E. Retention and uninterrupted-update option

Retain old inventories, exchange sets and their caches through the rollback
period. Only reclaim a generation after no store or in-flight reader uses it.
This guide deliberately contains no volume removal or automatic cache-pruning
commands. NOAA refreshing is manual; no scheduler is installed.

For uninterrupted serving during publication, use a new workspace such as
`noaa_20261119`, publish and verify it, then switch clients to its three groups.
The viewer lists workspaces published through `./enc deploy`. The legacy
`tune_cache.py`, `catalogue_smoke.py` and the helper functions above target
`noaa`. Use `check_sources.py --workspace NAME` to verify another workspace. A workspace switch is a client
configuration change, not an atomic alias provided by this plugin.

## Implementation references

- [Automated container launcher](../container/demo.sh)
- [Inventory preparation](../scripts/catalogue.py), [cache warming](../scripts/warm_catalogue.py)
  and [edge audit](../scripts/audit_edges.py)
- [REST publisher](../scripts/publish.py) and [portrayal compiler](../scripts/portrayal.py)
- [Cache tuning](../scripts/tune_cache.py) and [protocol smoke checks](../scripts/catalogue_smoke.py)
- [Design decisions](decisions.md), [catalogue validation](catalogue-validation.md)
  and [latest portrayal validation](portrayal-2026-11-17.md)
