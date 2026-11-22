package org.enc.geoserver;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.geotools.api.data.*;
import org.geotools.factory.CommonFactoryFinder;
import org.geotools.filter.function.EnvFunction;
import org.locationtech.jts.geom.*;

class CatalogueTest {
    @TempDir Path temp;
    static final GeometryFactory GF=new GeometryFactory();
    CatalogueIndex.Cell cell(String name,int scale,Envelope bounds,Map<String,Long> classes) {
        return new CatalogueIndex.Cell(name,Path.of(name+".000"),scale,Integer.parseInt(name.substring(2,3)),GF.toGeometry(bounds),classes,new double[]{2,10,20});
    }
    @Test void higherDetailMasksEveryLowerClassAndRetainsCoverageGaps() {
        var coarse=cell("US2TESTA",100000,new Envelope(0,4,0,4),Map.of("SOUNDG",20L));
        var detail=cell("US5TESTB",10000,new Envelope(1,3,1,3),Map.of("LNDARE",10L));
        var result=CatalogueIndex.quilt(List.of(coarse,detail),new Envelope(0,4,0,4),10000);
        assertEquals(List.of("US5TESTB","US2TESTA"),result.stream().map(s->s.cell().name()).toList());
        assertEquals(4,result.get(0).visible().getArea());assertEquals(12,result.get(1).visible().getArea());
        assertFalse(result.get(1).visible().contains(GF.createPoint(new Coordinate(2,2))));
        assertEquals(10,detail.safetyContour(5));
    }
    @Test void bathymetricOverlayRetainsTheUnderlyingChart() {
        var base=cell("US5TESTA",2000,new Envelope(0,2,0,2),Map.of("LIGHTS",1L));
        var overlay=new CatalogueIndex.Cell("3RBD0000",Path.of("overlay.000"),1000,99,
            GF.toGeometry(new Envelope(0,2,0,2)),Map.of("SOUNDG",10L),new double[0]);
        var result=CatalogueIndex.quilt(List.of(base,overlay),new Envelope(0,2,0,2),2000);
        assertEquals(2,result.size());
        assertTrue(result.stream().allMatch(s->s.visible().getArea()==4));
    }
    @Test void scaleRejectsOverDetailedCellsAndEqualScaleOwnershipIsStable() {
        var a=cell("US4TESTA",10000,new Envelope(0,4,0,4),Map.of());
        var b=cell("US4TESTB",10000,new Envelope(1,3,1,3),Map.of());
        assertTrue(CatalogueIndex.quilt(List.of(a,b),new Envelope(0,4,0,4),50000).isEmpty());
        var forward=CatalogueIndex.quilt(List.of(a,b),new Envelope(0,4,0,4),10000);
        var reverse=CatalogueIndex.quilt(List.of(b,a),new Envelope(0,4,0,4),10000);
        assertEquals(1,forward.size());assertEquals(forward.get(0).cell().name(),reverse.get(0).cell().name());
    }
    @Test void renderCallbackCarriesScaleAndClearsThreadOnCompletionAndFailure() {
        var callback=new CatalogueScaleCallback();
        var content=new org.geoserver.wms.WMSMapContent() {
            @Override public double getScaleDenominator(boolean dpi) { return 25000000; }
        };
        callback.beforeRender(content);assertEquals(25000000,RenderScale.CURRENT.get());
        assertEquals(25000000d,EnvFunction.getLocalValues().get("ENC_SCALE_DENOMINATOR"));
        callback.finished(null);assertNull(RenderScale.CURRENT.get());
        assertNull(EnvFunction.getLocalValues().get("ENC_SCALE_DENOMINATOR"));
        callback.beforeRender(content);callback.failed(new IllegalStateException("test"));
        assertNull(RenderScale.CURRENT.get());
    }
    @Test void factoryRequiresExactlyOneSource() {
        var f=new S57DataStoreFactory();
        var params=new HashMap<String,Object>(Map.of("dbtype","s57","cache",temp.toString(),"ogr2ogr","ogr2ogr"));
        assertThrows(java.io.IOException.class,()->f.createDataStore(params));
        params.put("file","cell.000");params.put("catalogue","catalogue.sqlite");
        assertThrows(java.io.IOException.class,()->f.createDataStore(params));
    }
    @Test void axisOrderDoesNotChangeCatalogueScale() throws Exception {
        var request=new org.geoserver.wms.GetMapRequest();
        var east=new org.geoserver.wms.WMSMapContent(request);
        var north=new org.geoserver.wms.WMSMapContent(request);
        east.setMapWidth(800);east.setMapHeight(600);north.setMapWidth(800);north.setMapHeight(600);
        east.getViewport().setBounds(new org.geotools.geometry.jts.ReferencedEnvelope(-74.06,-73.94,40.60,40.75,org.geotools.referencing.CRS.decode("EPSG:4326",true)));
        north.getViewport().setBounds(new org.geotools.geometry.jts.ReferencedEnvelope(40.60,40.75,-74.06,-73.94,org.geotools.referencing.CRS.decode("urn:ogc:def:crs:EPSG::4326",false)));
        assertEquals(CatalogueScaleCallback.renderingScale(east),CatalogueScaleCallback.renderingScale(north),1e-6);
        assertEquals(40.60,north.getViewport().getBounds().getMinX());
        east.dispose();north.dispose();
    }
    @Test @EnabledIfEnvironmentVariable(named="S57_CATALOGUE",matches=".+")
    void completeCatalogueDiscoveryDoesNotConvertAllCellsAndQueriesAreReadOnly() throws Exception {
        Path file=Path.of(System.getenv("S57_CATALOGUE"));
        CatalogueIndex index=new CatalogueIndex(file);
        assertTrue(index.cells.size()>7000);
        var params=Map.of("dbtype","s57","catalogue",file.toString(),"cache",temp.toString(),"ogr2ogr",System.getenv("OGR2OGR"),"namespace","urn:noaa");
        DataStore store=new S57DataStoreFactory().createDataStore(params);
        try {
            assertTrue(Arrays.asList(store.getTypeNames()).contains("SOUNDG"));
            assertEquals(0,Files.list(temp).count(),"Discovery must not import thousands of native datasets");
            var source=store.getFeatureSource("SOUNDG");assertFalse(source instanceof SimpleFeatureStore);
            var ff=CommonFactoryFinder.getFilterFactory();
            EnvFunction.setLocalValue("wms_scale_denominator",15000d);
            Query query=new Query("SOUNDG",ff.bbox("geom",-73.71,40.60,-73.69,40.62,"EPSG:4326"));
            query.setMaxFeatures(5);
            Set<String> ids=new HashSet<>();
            try(var reader=source.getFeatures(query).features()) {
                while(reader.hasNext()) {var f=reader.next();assertNotNull(f.getAttribute("_enc_cell"));assertTrue(ids.add(f.getID()));}
            }
            assertEquals(5,ids.size());
            assertThrows(java.io.IOException.class,()->store.getFeatureWriterAppend("SOUNDG",Transaction.AUTO_COMMIT));
        } finally {EnvFunction.clearLocalValues();store.dispose();}
    }
}
