package org.enc.geoserver;

import java.io.*;
import java.util.*;
import java.util.logging.Logger;
import java.util.zip.ZipInputStream;
import org.geoserver.catalog.*;
import org.geoserver.config.GeoServer;
import org.geoserver.config.GeoServerInitializer;
import org.geoserver.platform.resource.Resource;
import org.geotools.util.Version;

/** Installs the packaged resources before any data source is needed. */
public final class StyleLibraryInstaller implements GeoServerInitializer {
    private static final Logger LOG = Logger.getLogger(StyleLibraryInstaller.class.getName());
    private static final String OWNER = "enc.styleLibrary";

    @Override public void initialize(GeoServer server) throws IOException {
        if (!Boolean.parseBoolean(System.getProperty("enc.installStyles","true"))) return;
        Catalog catalog = server.getCatalog();
        Map<String,StyleInfo> existing = new HashMap<>();
        for (StyleInfo style : catalog.getStyles())
            if (style.getWorkspace() == null) existing.put(style.getName(),style);
        var store = catalog.getResourceLoader();
        try (var zip = new ZipInputStream(Objects.requireNonNull(getClass().getResourceAsStream("style-library.zip")))) {
            int count = 0;
            for (var entry = zip.getNextEntry(); entry != null; entry = zip.getNextEntry()) {
                String path = entry.getName();
                byte[] bytes = zip.readAllBytes();
                boolean isStyle = path.endsWith(".sld");
                String name = isStyle ? path.substring(0,path.length()-4) : "";
                StyleInfo registered = existing.get(name);
                if (isStyle && registered != null && (!"1".equals(registered.getMetadata().get(OWNER))
                        || !path.equals(registered.getFilename())))
                    throw new IOException("ENC style name already in use: "+name);
                var resource = store.get("styles/"+path);
                if (resource.getType() == Resource.Type.UNDEFINED) {
                    try (var out = resource.out()) { out.write(bytes); }
                } else {
                    try (var in = resource.in()) {
                        if (!Arrays.equals(bytes,in.readAllBytes()))
                            throw new IOException("ENC library resource differs from bundled version: "+path);
                    }
                }
                if (isStyle && registered == null) {
                    var style = catalog.getFactory().createStyle();
                    style.setName(name);
                    style.setFilename(path);
                    style.setFormat("sld");
                    style.setFormatVersion(new Version("1.0.0"));
                    style.getMetadata().put(OWNER,"1");
                    catalog.add(style);
                    count++;
                }
            }
            LOG.info("ENC style library ready; registered "+count+" new global styles");
        }
    }
}
