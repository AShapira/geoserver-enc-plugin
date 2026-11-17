package org.enc.geoserver;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.*;
import java.sql.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.locationtech.jts.geom.*;
import org.locationtech.jts.io.WKBWriter;

class EdgeMetadataTest {
    @TempDir Path temp;
    @Test void nativeEndpointsMasksOrientationAndScaleDependentOwners() throws Exception {
        Path raw=temp.resolve("native.sqlite"),out=temp.resolve("edges.sqlite");var gf=new GeometryFactory();var wkb=new WKBWriter();
        try(var db=DriverManager.getConnection("jdbc:sqlite:"+raw);var s=db.createStatement()){
            s.execute("CREATE TABLE ConnectedNode(RCID INTEGER,GEOMETRY BLOB)");
            try(var put=db.prepareStatement("INSERT INTO ConnectedNode VALUES(?,?)")){
                for(int i=1;i<=3;i++){put.setInt(1,i);put.setBytes(2,wkb.write(gf.createPoint(new Coordinate(i-1,0))));put.addBatch();}put.executeBatch();
            }
            s.execute("CREATE TABLE Edge(RCID INTEGER,GEOMETRY BLOB,NAME_RCID_0 INTEGER,NAME_RCID_1 INTEGER,QUAPOS INTEGER,POSACC REAL)");
            try(var put=db.prepareStatement("INSERT INTO Edge VALUES(?,?,?, ?,5,1.5)")){
                for(int i=1;i<=2;i++){put.setInt(1,i);put.setBytes(2,wkb.write(gf.createLineString()));put.setInt(3,i);put.setInt(4,i+1);put.addBatch();}put.executeBatch();
            }
            for(String table:List.of("RESARE","CBLSUB"))s.execute("CREATE TABLE "+table+"(RCID INTEGER,PRIM INTEGER,SCAMIN INTEGER,NAME_RCNM TEXT,NAME_RCID TEXT,ORNT TEXT,USAG TEXT,MASK TEXT)");
            // Higher-priority area is not display-base; it disappears above 10,000.
            s.execute("INSERT INTO RESARE VALUES(10,3,10000,'(2:130,130)','(2:1,2)','(2:1,1)','(2:1,1)','(2:2,1)')");
            s.execute("INSERT INTO CBLSUB VALUES(20,2,50000,'(2:130,130)','(2:1,2)','(2:2,1)','(2:1,1)','(2:2,1)')");
        }
        EdgeCache.build(raw,out,"fixture");var context=new EdgeContext(out);
        assertEquals(1,context.edges.get(1).getLength(),1e-12,"Empty native edge still joins both connected nodes");
        assertEquals(5,context.quality.get(1));
        assertTrue(context.line("CBLSUB",20,10000,null).isEmpty(),"Higher priority owns shared edge at inclusive SCAMIN");
        Geometry visible=context.line("CBLSUB",20,10001,null);
        assertEquals(1,visible.getLength(),1e-12,"MASK=1 edge remains hidden");
        assertEquals(1,visible.getCoordinates()[0].x,1e-12,"ORNT=2 reverses endpoints");
        assertEquals(0,visible.getCoordinates()[1].x,1e-12);
        assertTrue(context.line("CBLSUB",20,50001,null).isEmpty());
        assertNotEquals(-1,context.lookup("RESARE",10));
        assertEquals(-1,context.lookup("RESARE",999));
    }
    @Test void nativeLookupUsesOrderedListsAndNullAttributes() {
        assertTrue(S52Lookup.matches("COLOUR3",Map.of("COLOUR","3,4")));
        assertFalse(S52Lookup.matches("COLOUR3",Map.of("COLOUR","13")));
        assertTrue(S52Lookup.matches("COLOUR3,4,3",Map.of("COLOUR","3,4,3")));
        assertFalse(S52Lookup.matches("COLOUR3,4,3",Map.of("COLOUR","4,3,4")));
        assertTrue(S52Lookup.matches("QUAPOS?",Map.of()));
        assertTrue(S52Lookup.matches("QUAPOS2",Map.of("QUAPOS",2)));
    }
    @Test void conditionalOwnersQualityPartitionsAndSafetyPresetsStayAligned() throws Exception {
        Path raw=temp.resolve("quality-native.sqlite"),out=temp.resolve("quality.sqlite");var gf=new GeometryFactory();var wkb=new WKBWriter();
        try(var db=DriverManager.getConnection("jdbc:sqlite:"+raw);var s=db.createStatement()){
            s.execute("CREATE TABLE ConnectedNode(RCID INTEGER,GEOMETRY BLOB,QUAPOS INTEGER,POSACC REAL)");
            s.execute("CREATE TABLE IsolatedNode(RCID INTEGER,GEOMETRY BLOB,QUAPOS INTEGER,POSACC REAL)");
            for(String table:List.of("ConnectedNode","IsolatedNode"))try(var put=db.prepareStatement("INSERT INTO "+table+" VALUES(?,?,?,NULL)")){
                for(int i=1;i<=4;i++){put.setInt(1,i);put.setBytes(2,wkb.write(gf.createPoint(new Coordinate(i-1,0))));put.setInt(3,table.equals("IsolatedNode")?i+2:1);put.addBatch();}put.executeBatch();
            }
            s.execute("CREATE TABLE Edge(RCID INTEGER,GEOMETRY BLOB,NAME_RCID_0 INTEGER,NAME_RCID_1 INTEGER,QUAPOS INTEGER,POSACC REAL)");
            try(var put=db.prepareStatement("INSERT INTO Edge VALUES(?,?,?, ?,?,NULL)")){
                for(int i=1;i<=3;i++){put.setInt(1,i);put.setBytes(2,wkb.write(gf.createLineString()));put.setInt(3,i);put.setInt(4,i+1);put.setInt(5,i==2?5:1);put.addBatch();}put.executeBatch();
            }
            for(String table:List.of("COALNE","DEPCNT","RESARE","SOUNDG","DEPARE"))s.execute("CREATE TABLE "+table+"(RCID INTEGER,PRIM INTEGER,SCAMIN INTEGER,VALDCO REAL,DRVAL1 REAL,DRVAL2 REAL,RESTRN TEXT,NAME_RCNM TEXT,NAME_RCID TEXT,ORNT TEXT,USAG TEXT,MASK TEXT)");
            s.execute("INSERT INTO COALNE VALUES(1,2,1000,NULL,NULL,NULL,NULL,'130,130','1,2','1,1','1,1','2,2')");
            s.execute("INSERT INTO DEPCNT VALUES(10,2,10000,10,NULL,NULL,NULL,'130,130','1,2','1,1','1,1','2,2')");
            s.execute("INSERT INTO DEPCNT VALUES(20,2,10000,20,NULL,NULL,NULL,'130','3','1','1','2')");
            s.execute("INSERT INTO RESARE VALUES(30,3,50000,NULL,NULL,NULL,'7','130','3','2','1','2')");
            s.execute("INSERT INTO SOUNDG VALUES(40,1,50000,NULL,NULL,NULL,NULL,'110,110','1,3','255,255','255,255','255,255')");
            s.execute("INSERT INTO DEPARE VALUES(50,2,10000,NULL,4,6,NULL,'130','3','1','1','1')");
        }
        EdgeCache.build(raw,out,"quality-fixture");var five=new EdgeContext(out,5);var eleven=new EdgeContext(out,11);
        assertEquals(10,five.safetyContour);assertEquals(20,eleven.safetyContour);
        assertEquals(8,five.priority("DEPCNT",10));assertEquals(5,eleven.priority("DEPCNT",10));
        assertEquals(6,five.priority("RESARE",30));assertEquals(1,five.safety("DEPARE",50));assertEquals(0,eleven.safety("DEPARE",50));
        assertTrue(five.line("COALNE",1,20000,null).isEmpty(),"Safety contour owns the edges beyond native SCAMIN");
        var contours=five.lines("DEPCNT",10,20000,null);
        assertEquals(2,contours.all().getLength());assertEquals(1,contours.normal().getLength());assertEquals(1,contours.lowAccuracy().getLength());
        var coast=eleven.lines("COALNE",1,20000,null);
        assertEquals(2,coast.all().getLength(),"Display-base coast reappears when the old contour is no longer safe");
        assertEquals(1,coast.normal().getLength());assertEquals(1,coast.lowAccuracy().getLength());
        assertEquals(1,five.line("RESARE",30,5000,null).getLength(),"Conditional priority 6 beats ordinary contour priority 5");
        assertTrue(eleven.line("RESARE",30,5000,null).isEmpty(),"Safety promotion beats restricted area");
        assertTrue(five.line("DEPARE",50,5000,null).isEmpty(),"Safety promotion must not undo MASK=1");
        assertEquals(3,five.pointQuality("SOUNDG",40,gf.createPoint(new Coordinate(0,0))));
        assertEquals(5,five.pointQuality("SOUNDG",40,gf.createPoint(new Coordinate(2,0))));
        assertNull(five.pointQuality("SOUNDG",40,gf.createPoint(new Coordinate(1,0))),"Do not borrow another node's qualifier");
        for(int q:new int[]{0,1,10,11})assertFalse(EdgeContext.unreliable(q));
        for(int q=2;q<=9;q++)assertTrue(EdgeContext.unreliable(q));
        assertNotEquals(five.band(0),five.band(1),"Unscaled requests see every owner and need a separate cache band");
    }
    @Test void restrictionPriorityUsesWholeTokensAndOnlyTheConditionalLookup() {
        var ordinary=S52Lookup.INSTANCE.select("RESARE",3,Map.of("RESTRN","7"));
        for(String value:List.of("1","2","3","4","5","6","7","8","14","11,7"))assertEquals(6,ordinary.priority(Map.of("RESTRN",value)));
        for(String value:List.of("11","17","9","10","13","15"))assertEquals(ordinary.priority(),ordinary.priority(Map.of("RESTRN",value)));
        var special=S52Lookup.INSTANCE.select("RESARE",3,Map.of("CATREA","27","RESTRN","7"));
        if(!special.instruction().contains("CS(RESARE02)"))assertEquals(special.priority(),special.priority(Map.of("RESTRN","7")));
    }
    @Test void filledAreasDoNotOwnEdgesUnlessTheCompiledPortrayalDrawsThem() {
        assertFalse(S52Lookup.drawsLine("DEPARE",3,"CS(DEPARE01)"));
        assertTrue(S52Lookup.drawsLine("DRGARE",3,"CS(DEPARE01)"));
        assertTrue(S52Lookup.drawsLine("DEPARE",2,"CS(DEPARE01)"));
        assertFalse(S52Lookup.drawsLine("ACHARE",3,"CS(RESTRN01)"));
        assertTrue(S52Lookup.drawsLine("RESARE",3,"CS(RESARE02)"));
        assertTrue(S52Lookup.drawsLine("CTNARE",3,"CS(UNSUPPORTED)"));
        assertFalse(S52Lookup.drawsLine("COALNE",1,"CS(QUAPOS01)"));
    }
    @Test void sidecarRevisionIsSeparateFromSourceSnapshotIdentity() {
        Path base=Path.of("cache/abc.gpkg");assertEquals("abc-"+EdgeCache.REVISION+".edges.sqlite",EdgeCache.target(base).getFileName().toString());
        assertArrayEquals(new int[]{1,2,255},EdgeCache.integers("(3:1,2,255)"));
        assertArrayEquals(new int[0],EdgeCache.integers(null));
    }
    @Test void renderPermitsAreReleasedOnFailureAndRequestInitialization() {
        var callback=new CatalogueScaleCallback();int available=CatalogueScaleCallback.availablePermits();
        CatalogueScaleCallback.acquire();CatalogueScaleCallback.acquire();
        assertEquals(available-1,CatalogueScaleCallback.availablePermits());
        callback.failed(new RuntimeException("test"));assertEquals(available,CatalogueScaleCallback.availablePermits());
        CatalogueScaleCallback.acquire();callback.initRequest(null);assertEquals(available,CatalogueScaleCallback.availablePermits());
        callback.failed(new RuntimeException("already released"));assertEquals(available,CatalogueScaleCallback.availablePermits());
    }
}
