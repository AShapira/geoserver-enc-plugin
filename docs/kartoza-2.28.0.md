# Install S-57 on Kartoza 2.28.0

Use the stock `kartoza/geoserver:2.28.0` image and the 2.28.0 plugin ZIP. Kartoza searches for `/community_plugins/s57-plugin.zip` when `COMMUNITY_EXTENSIONS` includes `s57-plugin`. Its entrypoint changes ownership of that file. Stage a copy in the container before first start. Repeat the copy when recreating the container. Existing installations should retain their other settings, extension names and data volumes.

```bash
engine=${CONTAINER_ENGINE:-podman}
(cd dist && sha256sum -c geoserver-2.28.0-s57-plugin.zip.sha256)
"$engine" create --name enc-kartoza -p 127.0.0.1:18081:8080 \
  -e COMMUNITY_EXTENSIONS=s57-plugin -e FORCE_DOWNLOAD_COMMUNITY_EXTENSIONS=false \
  -v enc-kartoza-data:/opt/geoserver/data_dir \
  -v "$PWD/charts:/charts:ro" docker.io/kartoza/geoserver:2.28.0
"$engine" cp dist/geoserver-2.28.0-s57-plugin.zip enc-kartoza:/community_plugins/s57-plugin.zip
"$engine" start enc-kartoza
```

Create an **S-57 ENC (GDAL)** store with the server-side cell path, `/usr/bin/ogr2ogr` and a writable cache under the data directory. For offline installation save and load this exact vendor image along with the plugin ZIP. [Kartoza startup script](https://github.com/kartoza/docker-geoserver/blob/dca322a/scripts/start.sh)

Open the packaged [ENC viewer and search demo](http://127.0.0.1:18081/geoserver/enc/viewer/index.html) after publishing a feature type.
