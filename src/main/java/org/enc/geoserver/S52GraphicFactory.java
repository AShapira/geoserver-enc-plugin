package org.enc.geoserver;

import java.awt.*;
import java.awt.geom.*;
import java.awt.image.BufferedImage;
import java.net.URI;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.List;
import javax.swing.*;
import org.geotools.api.feature.Feature;
import org.geotools.api.filter.expression.Expression;
import org.geotools.renderer.style.ExternalGraphicFactory;

/** Native S-52 compound graphics. The reserved file URL is an identifier, never opened. */
public final class S52GraphicFactory implements ExternalGraphicFactory {
    private static final Map<String,Icon> CACHE=Collections.synchronizedMap(new LinkedHashMap<>(128,.75f,true) {
        @Override protected boolean removeEldestEntry(Map.Entry<String,Icon> entry) {return size()>512;}
    });
    @Override public Icon getIcon(Feature feature,Expression location,String format,int size) {
        if(!"image/x-enc-s52".equals(format)) return null;
        String url=location.evaluate(feature,String.class);
        if(url==null || !url.startsWith("file:/enc-s52/")) return null;
        Icon cached=CACHE.get(url);if(cached!=null) return cached;
        URI uri=URI.create(url.replace(" ","%20"));Map<String,String> params=new HashMap<>();
        if(uri.getRawQuery()!=null) for(String part:uri.getRawQuery().split("&")) {
            String[] pair=part.split("=",2);params.put(pair[0],pair.length==1?"":URLDecoder.decode(pair[1],StandardCharsets.UTF_8));
        }
        String palette=params.getOrDefault("palette","day");
        if(!Set.of("day","dusk","night").contains(palette)) throw new IllegalArgumentException("Unknown S-52 palette");
        String kind=uri.getPath().substring("/enc-s52/".length());
        int canvas=kind.equals("light")?200:64;
        BufferedImage image=new BufferedImage(canvas,canvas,BufferedImage.TYPE_INT_ARGB);
        Graphics2D g=image.createGraphics();g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
        int origin=canvas/2;
        try {
            if(kind.equals("sounding")) for(String glyph:soundingGlyphs(number(params,"depth",Double.NaN),number(params,"safety",5),params)) S52Symbols.INSTANCE.draw(g,palette,glyph,origin,origin);
            else if(kind.equals("light")) light(g,palette,params,origin);
            else if(kind.equals("topmark")) S52Symbols.INSTANCE.draw(g,palette,topmark((int)number(params,"shape",0),number(params,"floating",0)==1),origin,origin);
            else if(kind.equals("restriction")) {
                String glyph=restriction(params.get("restrn"),params.get("catrea"),"1".equals(params.get("area")));
                if(glyph!=null) S52Symbols.INSTANCE.draw(g,palette,glyph,origin,origin);
            }
            else if(kind.equals("wreck")) {
                double depth=number(params,"depth",Double.NaN),safety=number(params,"safety",5);
                int category=(int)number(params,"category",0),water=(int)number(params,"water",0);
                String glyph=Double.isFinite(depth)?depth<safety?"DANGER51":"DANGER52":
                    category==1&&water==3?"WRECKS04":category==4||category==5||water==1||water==2||water==4||water==5?"WRECKS01":"WRECKS05";
                S52Symbols.INSTANCE.draw(g,palette,glyph,origin,origin);
                if(Double.isFinite(depth)) {
                    if(codes(params.get("quasou")).contains(7)) S52Symbols.INSTANCE.draw(g,palette,"WRECKS07",origin,origin);
                    for(String digit:soundingGlyphs(depth,safety,params)) S52Symbols.INSTANCE.draw(g,palette,digit,origin,origin);
                }
            }
            else throw new IllegalArgumentException("Unknown S-52 graphic: "+kind);
        } finally {g.dispose();}
        Icon result=new ImageIcon(image);CACHE.put(url,result);return result;
    }
    static double number(Map<String,String> p,String key,double fallback) {
        try {double value=Double.parseDouble(p.getOrDefault(key,""));return Double.isFinite(value)?value:fallback;}catch(NumberFormatException ignored){return fallback;}
    }
    static Set<Integer> codes(String text) {
        Set<Integer> values=new HashSet<>();
        if(text!=null) for(String token:text.split(",")) try {values.add(Integer.parseInt(token.trim()));} catch(NumberFormatException ignored) {}
        return values;
    }
    static boolean any(Set<Integer> values,int... choices) {for(int choice:choices) if(values.contains(choice)) return true;return false;}
    /** RESTRN01/RESARE02 with plain boundaries, ranked list attributes. */
    static String restriction(String restrictions,String categories,boolean area) {
        Set<Integer> r=codes(restrictions),c=codes(categories);
        boolean danger=area&&any(c,1,8,9,12,14,19,21,25),info=area&&any(c,4,5,6,7,10,18,20,22,23,24);
        if(r.isEmpty()) return !area?null:danger?(info?"CTYARE71":"CTYARE51"):info?"INFARE51":"RSRDEF51";
        boolean other=any(r,9,10,11,12,13);
        if(any(r,7,8,14)) return any(r,1,2,3,4,5,6)||danger?"ENTRES61":other||info?"ENTRES71":"ENTRES51";
        if(any(r,1,2)) return any(r,3,4,5,6)||danger?"ACHRES61":other||info?"ACHRES71":area?"RESTRN51":"ACHRES51";
        if(any(r,3,4,5,6)) return danger?"FSHRES51":other||info?"FSHRES71":"FSHRES51";
        return other?"INFARE51":"RSRDEF51";
    }
    /** OpenCPN 5.12.4 SNDFRM02 metre branch; digits have individual atlas pivots. */
    static List<String> soundingGlyphs(double original,double safety,Map<String,String> p) {
        if(!Double.isFinite(original)) return List.of();
        double depth=original>40000?99999:original < -1000?0:original;
        depth+=depth>0?.01:-.01;
        String prefix=depth<=safety?"SOUNDS":"SOUNDG";
        List<String> result=new ArrayList<>();
        if(any(codes(p.get("tecsou")),6)) result.add(prefix+"B1");
        double quality=number(p,"quapos",0);
        if(any(codes(p.get("quasou")),3,4,5,8,9) || any(codes(p.get("status")),18) || quality>=2 && quality<10) result.add(prefix+"C2");
        int whole=(int)Math.abs(depth),fraction=(int)((Math.abs(depth)-whole)*10);
        if(Math.abs(depth)<31) {
            if(whole>=10) result.add(prefix+"2"+(whole/10));
            result.add(prefix+"1"+(whole%10));
            if(fraction>0) result.add(prefix+"5"+fraction);
        } else {
            String digits=Integer.toString(whole);
            String positions=switch(digits.length()) {case 1->"1";case 2->depth<0?"21":"10";case 3->"210";case 4->"2104";default->"32104";};
            for(int i=0;i<digits.length();i++) result.add(prefix+positions.charAt(i)+digits.charAt(i));
        }
        if(depth<0) result.add(prefix+"A1");
        return result;
    }
    static String topmark(int shape,boolean floating) {
        int[] fixed={0,22,24,30,32,33,34,85,86,36,28,27,14,25,26,88,87,0,30,33,34,33,34,34,22,24,30,86,89,22,86,14,30,0};
        int[] buoy={0,2,4,10,12,13,14,65,17,16,8,7,14,5,6,0,0,0,10,13,14,13,14,14,2,4,10,17,18,2,17,14,10,0};
        if(shape==0) return "QUESMRK1";
        int[] values=floating?buoy:fixed;
        return shape<0 || shape>=values.length || values[shape]==0?"TMARDEF"+(floating?2:1):String.format(Locale.ROOT,"TOPMAR%02d",values[shape]);
    }
    static void light(Graphics2D g,String palette,Map<String,String> p,int o) {
        var symbols=S52Symbols.INSTANCE;
        Set<Integer> cat=codes(p.get("catlit")),color=codes(p.get("colour"));
        if(any(cat,8,11)) {symbols.draw(g,palette,"LIGHTS82",o,o);return;}
        if(any(cat,9)) {symbols.draw(g,palette,"LIGHTS81",o,o);return;}
        double start=number(p,"sector1",Double.NaN),end=number(p,"sector2",Double.NaN),range=number(p,"range",9);
        String token=any(color,3)?"LITRD":any(color,4)?"LITGN":any(color,1,6,9,11)?"LITYW":"CHMGD";
        boolean sector=Double.isFinite(start)&&Double.isFinite(end);
        double sweep=sector?(end-start+360)%360:360;
        if(!sector && range<10) {
            String glyph=token.equals("LITRD")?"LIGHTS11":token.equals("LITGN")?"LIGHTS12":token.equals("LITYW")?"LIGHTS13":"LITDEF11";
            double orientation=number(p,"orientation",Double.NaN);
            if(any(cat,1,16) && !Double.isFinite(orientation)) {symbols.draw(g,palette,"QUESMRK1",o,o);return;}
            // The raster flare is already drawn at the library's 135-degree
            // orientation; only rotate its difference from that bearing.
            var transform=g.getTransform();g.rotate(Math.toRadians(any(cat,1,16)?orientation+180-135:0),o,o);symbols.draw(g,palette,glyph,o,o);g.setTransform(transform);return;
        }
        // OpenCPN's range-dependent radius is retained as a reference-viewer extension.
        double radiusMm=range<7?3:range<15?10:range<30?15:20;
        if(sector) radiusMm=Math.max(10,radiusMm);
        double radius=radiusMm/0.28;
        boolean obscured=any(codes(p.get("visibility")),3,7,8);
        if(!sector || sweep<1) {start=0;sweep=360;} else start=(start+180)%360; // bearings are from seaward
        Shape arc=new Arc2D.Double(o-radius,o-radius,2*radius,2*radius,90-start,-sweep,Arc2D.OPEN);
        g.setColor(symbols.color(palette,obscured?"CHBLK":"OUTLW"));g.setStroke(new BasicStroke(4));g.draw(arc);
        g.setColor(symbols.color(palette,obscured?"CHBRN":token));g.setStroke(new BasicStroke(obscured?1:2));g.draw(arc);
        if(sector && sweep<360) {
            g.setColor(symbols.color(palette,"CHBLK"));g.setStroke(new BasicStroke(.7f,BasicStroke.CAP_BUTT,BasicStroke.JOIN_MITER,10,new float[]{3,3},0));
            for(double angle:new double[]{start,start+sweep}) {double rad=Math.toRadians(angle),length=25/.28;g.draw(new Line2D.Double(o,o,o+length*Math.sin(rad),o-length*Math.cos(rad)));}
        }
    }
}
