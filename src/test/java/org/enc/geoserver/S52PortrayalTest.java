package org.enc.geoserver;

import static org.junit.jupiter.api.Assertions.*;
import java.awt.image.BufferedImage;
import java.util.*;
import org.geotools.factory.CommonFactoryFinder;
import org.geotools.feature.simple.*;
import org.geotools.data.memory.MemoryDataStore;
import org.locationtech.jts.geom.*;
import org.junit.jupiter.api.Test;

class S52PortrayalTest {
    @Test void restrictionAbsenceDoesNotCreateFalseHazardsAndListsAreRanked() {
        assertNull(S52GraphicFactory.restriction(null,null,false));
        assertNull(S52GraphicFactory.restriction("",null,false));
        assertEquals("INFARE51",S52GraphicFactory.restriction("11",null,false));
        assertEquals("ACHRES51",S52GraphicFactory.restriction("1",null,false));
        assertEquals("ENTRES61",S52GraphicFactory.restriction("1,7,11",null,false));
        assertEquals("ENTRES71",S52GraphicFactory.restriction("7,11",null,false));
        assertEquals("CTYARE71",S52GraphicFactory.restriction(null,"1,4",true));
        assertEquals("RESTRN51",S52GraphicFactory.restriction("1",null,true));
    }
    @Test void soundingDigitsKeepFractionalAndDryingGlyphsAndQuality() {
        assertEquals(List.of("SOUNDS12","SOUNDS53"),S52GraphicFactory.soundingGlyphs(2.3,5,Map.of()));
        assertEquals(List.of("SOUNDS12","SOUNDS53","SOUNDSA1"),S52GraphicFactory.soundingGlyphs(-2.3,5,Map.of()));
        assertEquals(List.of("SOUNDG13","SOUNDG01"),S52GraphicFactory.soundingGlyphs(31,5,Map.of()));
        assertEquals(List.of("SOUNDG21","SOUNDG12","SOUNDG03"),S52GraphicFactory.soundingGlyphs(123,5,Map.of()));
        assertEquals(List.of("SOUNDSB1","SOUNDSC2","SOUNDS12"),S52GraphicFactory.soundingGlyphs(2,5,Map.of("tecsou","6","quasou","3")));
        assertTrue(S52GraphicFactory.soundingGlyphs(Double.NaN,5,Map.of()).isEmpty());
    }
    @Test void referenceTopmarksSelectBuoyAndFixedVariants() {
        assertEquals("TOPMAR02",S52GraphicFactory.topmark(1,true));
        assertEquals("TOPMAR22",S52GraphicFactory.topmark(1,false));
        assertEquals("TOPMAR65",S52GraphicFactory.topmark(7,true));
        assertEquals("QUESMRK1",S52GraphicFactory.topmark(0,true));
        assertEquals("TMARDEF1",S52GraphicFactory.topmark(99,false));
    }
    @Test void nativeFactoryLoadsAllPalettesAndDrawsWrappedSectors() throws Exception {
        var ff=CommonFactoryFinder.getFilterFactory();var factory=new S52GraphicFactory();
        for(String palette:List.of("day","dusk","night")) for(String graphic:List.of(
            "sounding?depth=2.3&", "light?sector1=350&sector2=20&colour=3&", "topmark?shape=1&floating=1&")) {
            var icon=factory.getIcon(null,ff.literal("file:/enc-s52/"+graphic+"palette="+palette),"image/x-enc-s52",64);
            var image=new BufferedImage(icon.getIconWidth(),icon.getIconHeight(),BufferedImage.TYPE_INT_ARGB);
            var g=image.createGraphics();icon.paintIcon(null,g,0,0);g.dispose();int count=0;
            for(int y=0;y<image.getHeight();y++)for(int x=0;x<image.getWidth();x++)if((image.getRGB(x,y)>>>24)>0)count++;
            assertTrue(count>10,graphic+palette);
        }
        assertNull(factory.getIcon(null,ff.literal("https://example.com/icon"),"image/png",64));
    }
    @Test void customFunctionsAreDiscoveredAndHandleAbsentAttributes() {
        var ff=CommonFactoryFinder.getFilterFactory();
        assertEquals("Clr 5.2 m",ff.function("encFormat",ff.literal("Clr %3.1lf m"),ff.literal(5.2)).evaluate(null));
        assertEquals("Fl(2) R 6s 8m 5Nm",EncFunctionFactory.lightDescription(Arrays.asList(2,"(2)","3",6,8,5,null,null)).replace("6 s","6s").replace("8 m","8m").replace("5 Nm","5Nm"));
        assertEquals("",EncFunctionFactory.format(Arrays.asList("%s",null)));
    }
    @Test void floatingContextUsesCoLocatedBuoysNotNearbyFixedObjects() throws Exception {
        var type=new SimpleFeatureTypeBuilder();type.setName("BOYLAT");type.add("geom",Point.class);
        var geometry=new GeometryFactory();var schema=type.buildFeatureType();
        var store=new MemoryDataStore(SimpleFeatureBuilder.build(schema,new Object[]{geometry.createPoint(new Coordinate(1,2))},"buoy.1"));
        var context=new AtonContext(store);
        assertEquals(1,context.floating(geometry.createPoint(new Coordinate(1,2))));
        assertEquals(0,context.floating(geometry.createPoint(new Coordinate(1.00001,2))));
        store.dispose();
    }
    @Test void enrichedTopmarksSupportVirtualAttributeFilteringProjectionAndPagination() throws Exception {
        var type=new SimpleFeatureTypeBuilder();type.setName("BOYLAT");type.add("geom",Point.class);
        var geometry=new GeometryFactory();var point=geometry.createPoint(new Coordinate(1,2));
        var delegate=new MemoryDataStore(SimpleFeatureBuilder.build(type.buildFeatureType(),new Object[]{point},"buoy.1"));
        type=new SimpleFeatureTypeBuilder();type.setName("TOPMAR");type.add("geom",Point.class);type.add("TOPSHP",Integer.class);
        var schema=type.buildFeatureType();
        delegate.addFeatures(SimpleFeatureBuilder.build(schema,new Object[]{point,1},"top.1"),
            SimpleFeatureBuilder.build(schema,new Object[]{geometry.createPoint(new Coordinate(3,4)),1},"top.2"));
        var store=new S57DataStore(delegate);
        try {
            var ff=CommonFactoryFinder.getFilterFactory();
            var query=new org.geotools.api.data.Query("TOPMAR",ff.equals(ff.property("_enc_floating"),ff.literal(1)),new String[]{"TOPSHP","_enc_floating"});
            query.setMaxFeatures(1);
            try(var features=store.getFeatureSource("TOPMAR").getFeatures(query).features()) {
                assertTrue(features.hasNext());var f=features.next();assertEquals(2,f.getAttributeCount());assertEquals(1,f.getAttribute("_enc_floating"));assertFalse(features.hasNext());
            }
            query.setStartIndex(1);assertEquals(0,store.getFeatureSource("TOPMAR").getFeatures(query).size());
        } finally {store.dispose();}
    }
}
