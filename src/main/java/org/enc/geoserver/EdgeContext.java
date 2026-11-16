package org.enc.geoserver;

import java.io.IOException;
import java.nio.file.*;
import java.sql.*;
import java.util.*;
import org.locationtech.jts.geom.*;
import org.locationtech.jts.io.*;

/** Read-only precomputed topology; assemble visible edge chains without overlays. */
final class EdgeContext {
    record Feature(int lookup,int priority,boolean line,double scamin,int primitive) {
        boolean visible(double scale){return scale<=0||scamin<=0||scale<=scamin;}
    }
    record Link(int edge,int orientation,int usage,int mask) {}
    final Map<String,Feature> features=new HashMap<>();
    final Map<String,List<Link>> links=new HashMap<>();
    final Map<Integer,LineString> edges=new HashMap<>();
    final Map<Integer,List<Feature>> owners=new HashMap<>();
    final Map<Integer,Integer> quality=new HashMap<>();
    final double[] cutoffs;
    private final GeometryFactory gf=new GeometryFactory();
    private final LinkedHashMap<String,Geometry> cache=new LinkedHashMap<>(32,.75f,true);
    private long cacheBytes;
    private static final long MAX_BYTES=4L*1024*1024;
    EdgeContext(Path file) throws IOException {
        Set<Double> scales=new TreeSet<>();WKBReader reader=new WKBReader(gf);
        try(var db=DriverManager.getConnection("jdbc:sqlite:file:"+file.toAbsolutePath()+"?mode=ro");var s=db.createStatement()) {
            try(var rs=s.executeQuery("SELECT value FROM metadata WHERE key='format'")){
                if(!rs.next()||!EdgeCache.FORMAT.equals(rs.getString(1)))throw new IOException("Invalid native edge metadata");
            }
            try(var rs=s.executeQuery("SELECT value FROM metadata WHERE key='revision'")){
                if(!rs.next()||!EdgeCache.REVISION.equals(rs.getString(1)))throw new IOException("Stale native edge metadata");
            }
            try(var rs=s.executeQuery("SELECT class,rcid,lookup_id,priority,line,scamin,prim FROM features")){
                while(rs.next()){
                    var f=new Feature(rs.getInt(3),rs.getInt(4),rs.getBoolean(5),rs.getDouble(6),rs.getInt(7));
                    features.put(key(rs.getString(1),rs.getInt(2)),f);if(f.line()&&f.scamin()>0)scales.add(f.scamin());
                }
            }
            try(var rs=s.executeQuery("SELECT id,geom,quapos FROM edges")){while(rs.next()){edges.put(rs.getInt(1),(LineString)reader.read(rs.getBytes(2)));quality.put(rs.getInt(1),rs.getInt(3));}}
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
    int band(double scale){int result=Arrays.binarySearch(cutoffs,scale);return result>=0?result:-result-1;}
    static long bytes(Geometry g){return 128L+32L*g.getNumPoints()+64L*g.getNumGeometries();}
    synchronized Geometry line(String type,int rcid,double scale,Geometry original) {
        String id=key(type,rcid),cacheKey=id+":"+band(scale);Geometry found=cache.get(cacheKey);if(found!=null)return found;
        Feature f=features.get(id);var references=links.get(id);Geometry result;
        if(f==null||!f.line())return gf.createMultiLineString();
        else if(references==null||references.isEmpty())result=original==null?gf.createMultiLineString():original.getDimension()==2?original.getBoundary():original;
        else {
            List<LineString> lines=new ArrayList<>();List<Coordinate> chain=new ArrayList<>();
            for(Link link:references){
                boolean draw=f.visible(scale)&&link.mask()!=1;
                if(draw)for(Feature other:owners.getOrDefault(link.edge(),List.of()))if(other.visible(scale)&&other.priority()>f.priority()){draw=false;break;}
                LineString edge=edges.get(link.edge());
                if(!draw||edge==null){flush(chain,lines);continue;}
                Coordinate[] coordinates=edge.getCoordinates();if(link.orientation()==2){for(int i=0,j=coordinates.length-1;i<j;i++,j--){Coordinate c=coordinates[i];coordinates[i]=coordinates[j];coordinates[j]=c;}}
                if(!chain.isEmpty()&&!chain.get(chain.size()-1).equals2D(coordinates[0]))flush(chain,lines);
                for(int i=chain.isEmpty()?0:1;i<coordinates.length;i++)chain.add(coordinates[i]);
            }
            flush(chain,lines);result=gf.createMultiLineString(lines.toArray(LineString[]::new));
        }
        long cost=bytes(result);if(cost<=MAX_BYTES){cache.put(cacheKey,result);cacheBytes+=cost;var it=cache.entrySet().iterator();while(cacheBytes>MAX_BYTES&&it.hasNext()){cacheBytes-=bytes(it.next().getValue());it.remove();}}
        return result;
    }
    private void flush(List<Coordinate> chain,List<LineString> lines){if(chain.size()>=2)lines.add(gf.createLineString(chain.toArray(Coordinate[]::new)));chain.clear();}
}
