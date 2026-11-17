package org.enc.geoserver;

import java.io.IOException;
import java.io.Serializable;
import java.nio.file.Path;
import java.util.*;
import org.geotools.api.data.*;
import org.geotools.geopkg.GeoPkgDataStoreFactory;

/** Appears in GeoServer's New vector data source page through GeoTools SPI. */
public final class S57DataStoreFactory implements DataStoreFactorySpi {
    public static final Param TYPE = new Param("dbtype", String.class, "Database type", true, "s57");
    public static final Param FILE = new Param("file", String.class, "Local S-57 base cell (.000); leave empty for catalogue mode", false);
    public static final Param CATALOGUE = new Param("catalogue", String.class, "Prepared NOAA catalogue.sqlite (all active cells)", false);
    public static final Param POOL = new Param("cellPoolSize", Integer.class, "Maximum retained cell stores", false, 16);
    public static final Param SAFETY = new Param("safetyDepth", Double.class, "Safety depth in metres", false, 5.0);
    public static final Param CACHE = new Param("cache", String.class, "Writable ENC snapshot cache directory", true);
    public static final Param GDAL = new Param("ogr2ogr", String.class, "GDAL ogr2ogr executable", true, "ogr2ogr");
    public static final Param TIMEOUT = new Param("timeout", Integer.class, "Import timeout in seconds", false, 300);
    public static final Param NAMESPACE = new Param("namespace", String.class, "Namespace URI", false);

    @Override public String getDisplayName() { return "S-57 ENC (GDAL)"; }
    @Override public String getDescription() { return "Read-only S-57 cells or full catalogues via GDAL, with scale-aware coverage quilting"; }
    @Override public Param[] getParametersInfo() { return new Param[]{TYPE, FILE, CATALOGUE, CACHE, GDAL, TIMEOUT, POOL, SAFETY, NAMESPACE}; }
    @Override public boolean canProcess(Map<String, ?> params) { return "s57".equals(params.get("dbtype")); }
    @Override public boolean isAvailable() { return true; }
    @Override public Map<java.awt.RenderingHints.Key, ?> getImplementationHints() { return Collections.emptyMap(); }
    @Override public DataStore createNewDataStore(Map<String, ?> params) throws IOException { throw new IOException("S-57 store is read-only"); }

    @Override public DataStore createDataStore(Map<String, ?> params) throws IOException {
        if (!canProcess(params)) return null;
        String file = (String) FILE.lookUp(params);
        String cache = (String) CACHE.lookUp(params);
        String executable = (String) GDAL.lookUp(params);
        Integer seconds = (Integer) TIMEOUT.lookUp(params);
        int timeout = seconds == null ? 300 : seconds;
        if (timeout < 1 || timeout > 86400) throw new IOException("timeout must be 1..86400 seconds");
        String catalogue = (String) CATALOGUE.lookUp(params);
        String namespace = (String) NAMESPACE.lookUp(params);
        boolean single = file != null && !file.isBlank();
        boolean national = catalogue != null && !catalogue.isBlank();
        if (single == national) throw new IOException("Specify exactly one of file or catalogue");
        Double safety=(Double)SAFETY.lookUp(params);if(safety==null)safety=5.0;
        if(!Double.isFinite(safety)||safety<0)throw new IOException("Invalid safety depth");
        if (national) {
            Integer size = (Integer) POOL.lookUp(params);
            if (size == null) size = 16;
            if (safety == null) safety = 5.0;
            if (size < 1 || size > 256 || !Double.isFinite(safety) || safety < 0) throw new IOException("Invalid catalogue pool size or safety depth");
            return new CatalogueDataStore(Path.of(catalogue), Path.of(cache).toAbsolutePath(), executable, timeout, size, safety, namespace);
        }
        Path snapshot = GdalCache.materialize(Path.of(file), Path.of(cache).toAbsolutePath(), executable, timeout);
        Map<String, Serializable> gpkg = new HashMap<>();
        gpkg.put("dbtype", "geopkg"); gpkg.put("database", snapshot.toString());
        if (namespace != null) gpkg.put("namespace", namespace);
        Path metadata=EdgeCache.materialize(Path.of(file),snapshot,executable,timeout);
        DataStore delegate = new GeoPkgDataStoreFactory().createDataStore(gpkg);
        S57DataStore store = new S57DataStore(delegate,metadata,safety);
        if (namespace != null) store.setNamespaceURI(namespace);
        return store;
    }
}
