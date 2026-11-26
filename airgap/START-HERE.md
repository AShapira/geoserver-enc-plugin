# Install the S-57 extension offline

Verify the transfer manifest on the destination before extracting the kit. Load the saved stock GeoServer and operator images using the same container engine as the launcher. Extract the kit into its permanent directory so the server can retain its read-only file mounts.

```bash
sha256sum -c SHA256SUMS
export CONTAINER_ENGINE=podman   # or docker
"$CONTAINER_ENGINE" load -i stock.tar
"$CONTAINER_ENGINE" load -i operator.tar
unzip enc-kit.zip -d enc-kit
cd enc-kit
sha256sum -c SHA256SUMS
container/demo.sh --offline --empty
./enc deploy /absolute/path/to/local/exchange --workspace local_enc
```

For a catalog exported by the manager, use `./enc deploy --prepared /transfer/catalog.zip` in place of the exchange-directory command above. Compare `sha256sum /transfer/catalog.zip` to the checksum shown in the manager before deployment.

Open the chart viewer at http://127.0.0.1:18080/geoserver/enc/viewer/index.html. For Kartoza or a standalone WAR use the [extension install manual](airgap/README.md). For optional offline compilation and transfer details see the [air-gap guide](docs/airgap-deployment.md).
