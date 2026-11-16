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
