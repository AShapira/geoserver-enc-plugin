package org.enc.geoserver;

import static org.junit.jupiter.api.Assertions.*;
import java.io.IOException;
import java.nio.file.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.geotools.api.data.*;

class GdalCacheTest {
    @TempDir Path temp;
    @Test void fingerprintIncludesBaseAndEveryUpdateButNotOtherCells() throws Exception {
        Path base = Files.writeString(temp.resolve("US5TEST.000"), "base");
        String original = GdalCache.fingerprint(base,"GDAL test");
        Files.writeString(temp.resolve("OTHER.001"),"irrelevant");
        assertEquals(original,GdalCache.fingerprint(base,"GDAL test"));
        Path update = Files.writeString(temp.resolve("US5TEST.001"),"update");
        String withUpdate = GdalCache.fingerprint(base,"GDAL test");
        assertNotEquals(original, withUpdate);
        Files.writeString(update,"UPDATE"); // same size, different bytes
        assertNotEquals(withUpdate,GdalCache.fingerprint(base,"GDAL test"));
        assertNotEquals(original,GdalCache.fingerprint(base,"GDAL other"));
        assertEquals(2,GdalCache.exchangeFiles(base).size());
    }
    @Test void rejectsNonBaseFiles() throws Exception {
        Path file=Files.writeString(temp.resolve("cell.001"),"update");
        assertThrows(IOException.class,()->GdalCache.exchangeFiles(file));
    }
    @Test void serviceDiscoveryAndReadOnlyCreation() throws Exception {
        var factories=DataStoreFinder.getAvailableDataStores();
        boolean found=false;
        while(factories.hasNext()) if(factories.next() instanceof S57DataStoreFactory) found=true;
        assertTrue(found,"GeoTools must discover the plugin via its SPI file");
        var factory=new S57DataStoreFactory();
        assertFalse(factory.canProcess(Map.of("dbtype","geopkg")));
        assertThrows(IOException.class,()->factory.createNewDataStore(Map.of("dbtype","s57")));
    }
    @Test void rejectsErrorEvenWhenGdalExitsZero() throws Exception {
        Path log=temp.resolve("process.log");
        assertThrows(IOException.class,()->GdalCache.run(List.of("/bin/sh","-c","printf 'ERROR 1: malformed update'"),log,5));
    }
    @Test void processTimeoutIsBounded() {
        long start=System.nanoTime();
        assertThrows(IOException.class,()->GdalCache.run(List.of("/bin/sh","-c","exec sleep 20"),temp.resolve("process.log"),1));
        assertTrue((System.nanoTime()-start)/1e9<5);
    }
}
