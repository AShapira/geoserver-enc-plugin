package org.enc.geoserver;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.*;
import java.util.*;
import org.geotools.api.data.*;
import org.geotools.api.filter.Filter;
import org.geotools.api.filter.sort.SortOrder;
import org.geotools.factory.CommonFactoryFinder;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;

@EnabledIfEnvironmentVariable(named="S57_TEST_FILE",matches=".+")
class S57IntegrationTest {
    @TempDir Path temp;
    Map<String,Object> params() {
        return Map.of("dbtype","s57","file",System.getenv("S57_TEST_FILE"),"cache",temp.toString(),
            "ogr2ogr",System.getenv().getOrDefault("OGR2OGR","ogr2ogr"),"namespace","https://example.org/enc");
    }
    @Test void realCellReadFilteringPaginationBoundsAndReadOnly() throws Exception {
        DataStore store=new S57DataStoreFactory().createDataStore(params());
        try {
            assertTrue(Arrays.asList(store.getTypeNames()).contains("SOUNDG"));
            assertFalse(Arrays.asList(store.getTypeNames()).contains("DSID"));
            var source=store.getFeatureSource("SOUNDG");
            assertFalse(source instanceof SimpleFeatureStore);
            assertTrue(source.getCount(Query.ALL)>0);
            assertFalse(source.getBounds().isEmpty());
            assertNotNull(source.getSchema().getDescriptor("DEPTH"));
            assertNotNull(source.getSchema().getDescriptor("LNAM"));
            assertEquals("https://example.org/enc", source.getSchema().getName().getNamespaceURI());
            var ff=CommonFactoryFinder.getFilterFactory();
            Query q=new Query("SOUNDG",ff.greater(ff.property("DEPTH"),ff.literal(5)));
            q.setSortBy(ff.sort("DEPTH",SortOrder.ASCENDING)); q.setMaxFeatures(4); q.setStartIndex(1);
            int count=0; double previous=5;
            try(var features=source.getFeatures(q).features()) {
                while(features.hasNext()) {
                    double depth=((Number)features.next().getAttribute("DEPTH")).doubleValue();
                    assertTrue(depth>=previous); previous=depth; count++;
                }
            }
            assertEquals(4,count);
            Query absent=new Query("SOUNDG",ff.bbox(source.getSchema().getGeometryDescriptor().getLocalName(),0,0,1,1,"EPSG:4326"));
            assertEquals(0,source.getFeatures(absent).size());
            assertThrows(java.io.IOException.class,()->store.getFeatureWriterAppend("SOUNDG",Transaction.AUTO_COMMIT));
            Query projected=new Query("SOUNDG",Filter.INCLUDE,new String[]{"DEPTH"}); projected.setMaxFeatures(1);
            try(var features=source.getFeatures(projected).features()) { assertEquals(1,features.next().getAttributeCount()); }
        } finally { store.dispose(); }
    }
    @Test void unchangedCellReusesSnapshot() throws Exception {
        DataStore one=new S57DataStoreFactory().createDataStore(params()); one.dispose();
        Path cache;
        try(var files=Files.list(temp)){ cache=files.filter(p->p.toString().endsWith(".gpkg")).findFirst().orElseThrow(); }
        var modified=Files.getLastModifiedTime(cache);
        DataStore two=new S57DataStoreFactory().createDataStore(params()); two.dispose();
        assertEquals(modified,Files.getLastModifiedTime(cache));
        try(var files=Files.list(temp)){ assertEquals(1,files.filter(p->p.toString().endsWith(".gpkg")).count()); }
    }
    @Test void missingIntermediateUpdateMustNotSilentlyPublishStaleData() throws Exception {
        Path original=Path.of(System.getenv("S57_TEST_FILE"));
        String stem=original.getFileName().toString().replaceFirst("\\.000$","");
        Path update=original.resolveSibling(stem+".001");
        org.junit.jupiter.api.Assumptions.assumeTrue(Files.exists(update),"Requires a NOAA sample with .001 update");
        Path source=Files.createDirectory(temp.resolve("source"));
        Path base=Files.copy(original,source.resolve(original.getFileName()));
        Files.copy(update,source.resolve(stem+".002"));
        Path cache=temp.resolve("cache");
        assertThrows(java.io.IOException.class,()->GdalCache.materialize(base,cache,
            System.getenv().getOrDefault("OGR2OGR","ogr2ogr"),30));
        try(var files=Files.list(cache)){ assertEquals(0,files.filter(p->p.toString().endsWith(".gpkg")).count()); }
    }
}
