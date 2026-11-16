package org.enc.geoserver;

import java.awt.*;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.util.*;
import javax.imageio.ImageIO;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Element;

/** Pinned OpenCPN atlas, preserving each S-52 symbol's origin and colour table. */
final class S52Symbols {
    record Glyph(int x,int y,int width,int height,int pivotX,int pivotY) {}
    final Map<String,Glyph> glyphs=new HashMap<>();
    final Map<String,BufferedImage> atlases=new HashMap<>();
    final Map<String,Map<String,Color>> colors=new HashMap<>();
    static final S52Symbols INSTANCE=new S52Symbols();
    private S52Symbols() {
        try {
            var factory=DocumentBuilderFactory.newInstance();
            factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl",true);
            var document=factory.newDocumentBuilder().parse(getClass().getResourceAsStream("s52/chartsymbols.xml"));
            var symbols=document.getElementsByTagName("symbol");
            for(int i=0;i<symbols.getLength();i++) {
                Element symbol=(Element)symbols.item(i);
                Element bitmap=(Element)symbol.getElementsByTagName("bitmap").item(0);
                if(bitmap==null) continue;
                Element pos=(Element)bitmap.getElementsByTagName("graphics-location").item(0);
                Element pivot=(Element)bitmap.getElementsByTagName("pivot").item(0);
                glyphs.put(symbol.getElementsByTagName("name").item(0).getTextContent(),new Glyph(n(pos,"x"),n(pos,"y"),n(bitmap,"width"),n(bitmap,"height"),n(pivot,"x"),n(pivot,"y")));
            }
            var tables=document.getElementsByTagName("color-table");
            for(int i=0;i<tables.getLength();i++) {
                Element table=(Element)tables.item(i);
                String palette=switch(table.getAttribute("name")) {case "DAY_BRIGHT"->"day";case "DUSK"->"dusk";case "NIGHT"->"night";default->null;};
                if(palette==null) continue;
                String filename=((Element)table.getElementsByTagName("graphics-file").item(0)).getAttribute("name");
                atlases.put(palette,ImageIO.read(getClass().getResourceAsStream("s52/"+filename)));
                Map<String,Color> values=new HashMap<>();var entries=table.getElementsByTagName("color");
                for(int j=0;j<entries.getLength();j++) {Element c=(Element)entries.item(j);values.put(c.getAttribute("name"),new Color(n(c,"r"),n(c,"g"),n(c,"b")));}
                colors.put(palette,Map.copyOf(values));
            }
        } catch(Exception error) {throw new ExceptionInInitializerError(error);}
    }
    private static int n(Element e,String name) {return Integer.parseInt(e.getAttribute(name));}
    Color color(String palette,String token) {return colors.get(palette).getOrDefault(token,Color.MAGENTA);}
    void draw(Graphics2D g,String palette,String name,int x,int y) {
        Glyph glyph=glyphs.get(name);
        if(glyph==null) glyph=glyphs.get("QUESMRK1");
        int left=x-glyph.pivotX(),top=y-glyph.pivotY();
        g.drawImage(atlases.get(palette),left,top,left+glyph.width(),top+glyph.height(),glyph.x(),glyph.y(),glyph.x()+glyph.width(),glyph.y()+glyph.height(),null);
    }
}
