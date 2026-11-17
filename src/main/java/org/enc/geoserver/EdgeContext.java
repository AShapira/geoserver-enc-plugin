package org.enc.geoserver;

import java.io.IOException;
import java.nio.file.*;
import java.sql.*;
import java.util.*;
import org.locationtech.jts.geom.*;
import org.locationtech.jts.io.*;

/** Read-only topology and conditional decisions, resolved for one store's safety preset. */
final class EdgeContext {
    record Feature(int lookup,int priority,boolean line,double scamin,int primitive,boolean safety) {
        boolean visible(double scale){return scale<=0||scamin<=0||scale<=scamin;}
    }
    record Link(int edge,int orientation,int usage,int mask) {}
    record Lines(Geometry all,Geometry normal,Geometry lowAccuracy) {
        long bytes(){return EdgeContext.bytes(all)+(normal==all?0:EdgeContext.bytes(normal))+(lowAccuracy==all?0:EdgeContext.bytes(lowAccuracy));}
    }
    final Map<String,Feature> features=new HashMap<>();
    final Map<String,List<Link>> links=new HashMap<>();
    final Map<Integer,LineString> edges=new HashMap<>();
    final Map<Integer,List<Feature>> owners=new HashMap<>();
    final Map<Integer,Integer> quality=new HashMap<>();
    final Map<String,Map<Coordinate,Integer>> pointQuality=new HashMap<>();
    final double[] cutoffs;
    final double safetyContour;
    private final GeometryFactory gf=new GeometryFactory();
    private final Geometry empty=gf.createMultiLineString();
    private final Lines noLines=new Lines(empty,empty,empty);
    private final LinkedHashMap<String,Lines> cache=new LinkedHashMap<>(32,.75f,true);
    private long cacheBytes;
    private static final long MAX_BYTES=4L*1024*1024;
    EdgeContext(Path file) throws IOException {this(file,5);}
    EdgeContext(Path file,double safetyDepth) throws IOException {
        Set<Double> scales=new TreeSet<>();WKBReader reader=new WKBReader(gf);
        try(var db=DriverManager.getConnection("jdbc:sqlite:file:"+file.toAbsolutePath()+"?mode=ro");var s=db.createStatement()) {
            try(var rs=s.executeQuery("SELECT value FROM metadata WHERE key='format'")){
                if(!rs.next()||!EdgeCache.FORMAT.equals(rs.getString(1)))throw new IOException("Invalid native edge metadata");
            }
            try(var rs=s.executeQuery("SELECT value FROM metadata WHERE key='revision'")){
                if(!rs.next()||!EdgeCache.REVISION.equals(rs.getString(1)))throw new IOException("Stale native edge metadata");
            }
            try(var q=db.prepareStatement("SELECT min(depth1) FROM features WHERE class='DEPCNT' AND depth1>=?")){
                q.setDouble(1,safetyDepth);try(var rs=q.executeQuery()){rs.next();double v=rs.getDouble(1);safetyContour=rs.wasNull()?Double.NaN:v;}
            }
            try(var rs=s.executeQuery("SELECT class,rcid,lookup_id,priority,line,scamin,prim,contour,depth1,depth2 FROM features")){
                while(rs.next()){
                    String type=rs.getString(1);Double low=rs.getObject(9) instanceof Number n?n.doubleValue():null;
                    Double high=rs.getObject(10) instanceof Number n?n.doubleValue():low;
                    boolean safe=rs.getBoolean(8)&&low!=null&&(type.equals("DEPARE")&&low<=safetyDepth&&high!=null&&high>=safetyDepth
                        ||Math.abs(low-safetyDepth)<1e-4||Math.abs(low-safetyContour)<1e-4);
                    var f=new Feature(rs.getInt(3),safe?8:rs.getInt(4),rs.getBoolean(5),safe?0:rs.getDouble(6),rs.getInt(7),safe);
                    features.put(key(type,rs.getInt(2)),f);if(f.line()&&f.scamin()>0)scales.add(f.scamin());
                }
            }
            try(var rs=s.executeQuery("SELECT id,geom,quapos FROM edges")){while(rs.next()){edges.put(rs.getInt(1),(LineString)reader.read(rs.getBytes(2)));quality.put(rs.getInt(1),rs.getInt(3));}}
            try(var rs=s.executeQuery("SELECT class,rcid,geom,quapos FROM point_quality WHERE quapos IS NOT NULL")){while(rs.next()){
                var points=pointQuality.computeIfAbsent(key(rs.getString(1),rs.getInt(2)),k->new HashMap<>());
                for(Coordinate coordinate:reader.read(rs.getBytes(3)).getCoordinates())points.put(coordinate,rs.getInt(4));
            }}
            try(var rs=s.executeQuery("SELECT class,rcid,edge,orientation,usage,mask FROM links ORDER BY class,rcid,seq")){
                while(rs.next()){
                    String key=key(rs.getString(1),rs.getInt(2));var link=new Link(rs.getInt(3),rs.getInt(4),rs.getInt(5),rs.getInt(6));
                    links.computeIfAbsent(key,k->new ArrayList<>()).add(link);Feature f=features.get(key);
                    if(f!=null&&f.line()&&link.mask()!=1)owners.computeIfAbsent(link.edge(),k->new ArrayList<>()).add(f);
                }
            }
        }catch(SQLException|ParseException e){throw new IOException("Cannot read native edge metadata "+file,e);}
        cutoffs=scales.stream().mapToDouble(Double::doubleValue).toArray();
    }
    static String key(String type,int rcid){return type+":"+rcid;}
    int lookup(String type,int rcid){Feature f=features.get(key(type,rcid));return f==null?-1:f.lookup();}
    int priority(String type,int rcid){Feature f=features.get(key(type,rcid));return f==null?-1:f.priority();}
    int safety(String type,int rcid){Feature f=features.get(key(type,rcid));return f!=null&&f.safety()?1:0;}
    Integer pointQuality(String type,int rcid,Geometry original) {
        if(original==null||original.isEmpty()||original.getDimension()!=0)return null;
        // The GDAL snapshot splits SOUNDG multipoints. Match that coordinate to its
        // own spatial primitive, never spread a qualifier over unrelated nodes.
        return pointQuality.getOrDefault(key(type,rcid),Map.of()).get(original.getCoordinate());
    }
    static boolean unreliable(int quapos){return quapos>=2&&quapos<=9;}
    int band(double scale){if(scale<=0)return cutoffs.length+1;int result=Arrays.binarySearch(cutoffs,scale);return result>=0?result:-result-1;}
    static long bytes(Geometry g){return 128L+32L*g.getNumPoints()+64L*g.getNumGeometries();}
    Geometry line(String type,int rcid,double scale,Geometry original){return lines(type,rcid,scale,original).all();}
    synchronized Lines lines(String type,int rcid,double scale,Geometry original) {
        String id=key(type,rcid),cacheKey=id+":"+band(scale);Lines found=cache.get(cacheKey);if(found!=null)return found;
        Feature f=features.get(id);var references=links.get(id);Lines result;
        if(f==null||!f.line()||!f.visible(scale))return noLines;
        if(references==null||references.isEmpty()){
            Geometry fallback=original==null?empty:original.getDimension()==2?original.getBoundary():original;
            // A missing spatial qualifier is not evidence of low accuracy. Do not
            // cache source-dependent fallback geometries under only RCID.
            return new Lines(fallback,fallback,empty);
        }else {
            List<LineString> all=new ArrayList<>(),normal=new ArrayList<>(),low=new ArrayList<>();
            List<Coordinate> chain=new ArrayList<>(),normalChain=new ArrayList<>(),lowChain=new ArrayList<>();
            for(Link link:references){
                boolean draw=link.mask()!=1;
                if(draw)for(Feature other:owners.getOrDefault(link.edge(),List.of()))if(other.visible(scale)&&other.priority()>f.priority()){draw=false;break;}
                LineString edge=edges.get(link.edge());
                if(!draw||edge==null){flush(chain,all);flush(normalChain,normal);flush(lowChain,low);continue;}
                Coordinate[] coordinates=edge.getCoordinates();if(link.orientation()==2){for(int i=0,j=coordinates.length-1;i<j;i++,j--){Coordinate c=coordinates[i];coordinates[i]=coordinates[j];coordinates[j]=c;}}
                append(coordinates,chain,all);
                if(unreliable(quality.getOrDefault(link.edge(),0))){flush(normalChain,normal);append(coordinates,lowChain,low);}
                else {flush(lowChain,low);append(coordinates,normalChain,normal);}
            }
            flush(chain,all);flush(normalChain,normal);flush(lowChain,low);
            Geometry whole=geometry(all);result=new Lines(whole,low.isEmpty()?whole:geometry(normal),normal.isEmpty()?whole:geometry(low));
        }
        long cost=result.bytes();if(cost<=MAX_BYTES){cache.put(cacheKey,result);cacheBytes+=cost;var it=cache.entrySet().iterator();while(cacheBytes>MAX_BYTES&&it.hasNext()){cacheBytes-=it.next().getValue().bytes();it.remove();}}
        return result;
    }
    private Geometry geometry(List<LineString> lines){return lines.isEmpty()?empty:gf.createMultiLineString(lines.toArray(LineString[]::new));}
    private void append(Coordinate[] coordinates,List<Coordinate> chain,List<LineString> lines){
        if(!chain.isEmpty()&&!chain.get(chain.size()-1).equals2D(coordinates[0]))flush(chain,lines);
        for(int i=chain.isEmpty()?0:1;i<coordinates.length;i++)chain.add(coordinates[i]);
    }
    private void flush(List<Coordinate> chain,List<LineString> lines){if(chain.size()>=2)lines.add(gf.createLineString(chain.toArray(Coordinate[]::new)));chain.clear();}
}
