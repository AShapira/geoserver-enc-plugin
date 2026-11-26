# Transfer the S-57 extension and chart service

On the connected machine run the exporter from the source checkout. The default transfer includes both standalone plugin ZIPs, the source and operator kit, the stock OSGeo 3.0.2 GDAL image and the matching operator image. The optional builder export also contains the JDK/Maven/GDAL builder and its populated Maven repository. Use matching Linux CPU architectures on both machines.

```bash
export CONTAINER_ENGINE=podman     # or docker
airgap/export.sh /transfer/enc --with-builder
./enc prepare --archive /path/to/cells.zip --out /transfer/exchange
```

Transfer the output directory and the prepared exchange. Verify the manifest and follow the [destination instructions](../airgap/START-HERE.md). Each plugin ZIP also has an individual SHA-256 file. To recompile with networking disabled, run these commands from the extracted kit with the transfer files one directory above it.

```bash
"$CONTAINER_ENGINE" load -i ../builder.tar
mkdir -p .runtime/plugin-maven
tar -xzf ../maven.tar.gz -C .runtime/plugin-maven
container/build-plugins.sh --offline
container/demo.sh --offline --empty --recreate
```

For a new chart edition, prepare and transfer the complete exchange directory, then run the same deploy command for its workspace. The operator stages and validates the new generation before switching the store. An offline rehearsal can use a single local exchange. The full NOAA launcher downloads chart inputs when its catalogue volume is empty.

To start the NOAA demo offline, stage the matched `ENCProdCat.xml` and `All_ENCs.zip` files in the catalogue volume’s `downloads/` directory. For the default container the volume name is `geoserver-enc-catalogue`. Run `container/demo.sh --offline` to index, publish, prewarm and seed that delivery. The offline launcher checks the preloaded images and archives before using them.
