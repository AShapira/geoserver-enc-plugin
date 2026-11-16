package org.enc.geoserver;

import java.io.*;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.sql.*;
import java.util.*;
import java.util.concurrent.*;
import org.locationtech.jts.geom.*;
import org.locationtech.jts.io.*;

/** Atomic, immutable native topology/lookup sidecars; GDAL stays outside the JVM. */
public final class EdgeCache {
    static final String FORMAT="enc-edges-1";
    static final String REVISION=revision();
    private static String revision(){try {
        var digest=MessageDigest.getInstance("SHA-256");digest.update((FORMAT+":lookup-2:conditional-lines-endpoints-mask-orientation").getBytes(StandardCharsets.UTF_8));
        try(var in=EdgeCache.class.getResourceAsStream("s52/chartsymbols.xml")){digest.update(in.readAllBytes());}
        return HexFormat.of().formatHex(digest.digest()).substring(0,16);
    }catch(Exception e){throw new ExceptionInInitializerError(e);}}
    static Path target(Path snapshot){return snapshot.resolveSibling(snapshot.getFileName().toString().replace(".gpkg","-"+REVISION+".edges.sqlite"));}
    static String quote(String name){return "\""+name.replace("\"","\"\"")+"\"";}
    static int[] integers(Object value) {
        if(value==null || value.toString().isBlank())return new int[0];
        String text=value.toString();if(text.startsWith("("))text=text.substring(text.indexOf(':')+1,text.length()-1);
        if(text.isEmpty())return new int[0];return Arrays.stream(text.split(",")).map(String::trim).mapToInt(Integer::parseInt).toArray();
    }
    static Path materialize(Path base,Path snapshot,String executable,int timeout) throws IOException {
        Path target=target(snapshot);if(Files.isRegularFile(target))return target;
        Files.createDirectories(target.getParent());
        // JVM lock prevents OverlappingFileLockException; file lock coordinates processes.
        synchronized(EdgeCache.class){
            if(Files.isRegularFile(target))return target;
            return createLocked(base,snapshot,executable,timeout);
        }
    }
    private static Path createLocked(Path base,Path snapshot,String executable,int timeout) throws IOException {
        Path target=target(snapshot),lockPath=target.resolveSibling(target.getFileName()+".lock");
        try(var channel=FileChannel.open(lockPath,StandardOpenOption.CREATE,StandardOpenOption.WRITE);var lock=channel.lock()) {
            if(Files.isRegularFile(target))return target;
            Path directory=Files.createTempDirectory(target.getParent(),"edge-import-");
            try {
                Path raw=directory.resolve("native.sqlite"),out=directory.resolve("edges.sqlite"),log=directory.resolve("gdal.log");
                String version=GdalCache.run(List.of(executable,"--version"),log,timeout);
                String identity=GdalCache.fingerprint(base,version);
                if(!snapshot.getFileName().toString().equals(identity+".gpkg"))throw new IOException("Snapshot/source identity mismatch");
                GdalCache.run(List.of(executable,"-f","SQLite",raw.toString(),base.toString(),"-oo","UPDATES=APPLY",
                    "-oo","RETURN_LINKAGES=ON","-oo","RETURN_PRIMITIVES=ON","-oo","LIST_AS_STRING=ON",
                    "-mapFieldType","StringList=String,IntegerList=String","-lco","FORMAT=WKB","-lco","LAUNDER=NO","-unsetFieldWidth"),log,timeout);
                GdalCache.validateAppliedUpdates(base,raw);
                build(raw,out,identity);
                if(!identity.equals(GdalCache.fingerprint(base,version)))throw new IOException("ENC changed during topology import");
                Files.move(out,target,StandardCopyOption.ATOMIC_MOVE);return target;
            } finally {
                try(var files=Files.list(directory)){for(Path p:files.toList())Files.deleteIfExists(p);}Files.deleteIfExists(directory);
            }
        }
    }
    static void build(Path raw,Path out,String identity) throws IOException {
        var gf=new GeometryFactory();var reader=new WKBReader(gf);var writer=new WKBWriter(2);
        try(var in=DriverManager.getConnection("jdbc:sqlite:"+raw);var db=DriverManager.getConnection("jdbc:sqlite:"+out);var statement=db.createStatement()) {
            statement.execute("PRAGMA journal_mode=OFF");statement.execute("PRAGMA synchronous=OFF");db.setAutoCommit(false);
            statement.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)");
            statement.execute("CREATE TABLE edges(id INTEGER PRIMARY KEY,geom BLOB NOT NULL,start_node INTEGER,end_node INTEGER,quapos INTEGER,posacc REAL)");
            statement.execute("CREATE TABLE features(class TEXT,rcid INTEGER,lookup_id INTEGER,priority INTEGER,line INTEGER,scamin REAL,prim INTEGER,PRIMARY KEY(class,rcid)) WITHOUT ROWID");
            statement.execute("CREATE TABLE links(class TEXT,rcid INTEGER,seq INTEGER,edge INTEGER,orientation INTEGER,usage INTEGER,mask INTEGER,PRIMARY KEY(class,rcid,seq)) WITHOUT ROWID");
            Set<String> tables=new TreeSet<>();try(var s=in.createStatement();var rs=s.executeQuery("SELECT name FROM sqlite_master WHERE type='table'")){while(rs.next())tables.add(rs.getString(1));}
            Map<Integer,Coordinate> nodes=new HashMap<>();Set<Integer> edgeIds=new HashSet<>();
            if(tables.contains("ConnectedNode"))try(var s=in.createStatement();var rs=s.executeQuery("SELECT RCID,GEOMETRY FROM ConnectedNode")) {
                while(rs.next()){byte[] b=rs.getBytes(2);if(b!=null){Geometry g=reader.read(b);if(!g.isEmpty())nodes.put(rs.getInt(1),g.getCoordinate());}}
            }
            if(tables.contains("Edge"))try(var s=in.createStatement();var rs=s.executeQuery("SELECT RCID,GEOMETRY,NAME_RCID_0,NAME_RCID_1,QUAPOS,POSACC FROM Edge");var put=db.prepareStatement("INSERT INTO edges VALUES(?,?,?,?,?,?)")) {
                while(rs.next()) {
                    int id=rs.getInt(1),start=rs.getInt(3),end=rs.getInt(4);Coordinate a=nodes.get(start),b=nodes.get(end);
                    if(a==null||b==null)throw new IOException("Missing connected node for edge "+id);
                    List<Coordinate> coordinates=new ArrayList<>();coordinates.add(a);
                    byte[] bytes=rs.getBytes(2);if(bytes!=null)Collections.addAll(coordinates,reader.read(bytes).getCoordinates());coordinates.add(b);
                    put.setInt(1,id);put.setBytes(2,writer.write(gf.createLineString(coordinates.toArray(Coordinate[]::new))));
                    put.setInt(3,start);put.setInt(4,end);put.setObject(5,rs.getObject(5));put.setObject(6,rs.getObject(6));put.addBatch();edgeIds.add(id);
                }put.executeBatch();
            }
            try(var feature=db.prepareStatement("INSERT INTO features VALUES(?,?,?,?,?,?,?)");var link=db.prepareStatement("INSERT INTO links VALUES(?,?,?,?,?,?,?)")) {
                for(String type:tables) {
                    if(!type.matches("[A-Z][A-Z0-9_]{4,7}") || type.startsWith("M_") || type.startsWith("C_"))continue;
                    try(var s=in.createStatement();var rs=s.executeQuery("SELECT * FROM "+quote(type))) {
                        var md=rs.getMetaData();List<String> names=new ArrayList<>();for(int c=1;c<=md.getColumnCount();c++)names.add(md.getColumnName(c));
                        if(!names.contains("PRIM"))continue;
                        while(rs.next()) {
                            Map<String,Object> attrs=new HashMap<>();for(int c=1;c<=names.size();c++)if(!names.get(c-1).equals("GEOMETRY"))attrs.put(names.get(c-1),rs.getObject(c));
                            int rcid=rs.getInt("RCID"),prim=rs.getInt("PRIM");var rule=S52Lookup.INSTANCE.select(type,prim,attrs);
                            double scamin=attrs.get("SCAMIN") instanceof Number n?n.doubleValue():0;
                            if(rule!=null&&rule.base())scamin=0;
                            feature.setString(1,type);feature.setInt(2,rcid);feature.setInt(3,rule==null?-1:rule.id());feature.setInt(4,rule==null?-1:rule.priority());
                            feature.setInt(5,rule!=null&&rule.line()?1:0);feature.setDouble(6,scamin);feature.setInt(7,prim);feature.addBatch();
                            int[] ids=integers(attrs.get("NAME_RCID")),kinds=integers(attrs.get("NAME_RCNM")),orient=integers(attrs.get("ORNT")),usage=integers(attrs.get("USAG")),mask=integers(attrs.get("MASK"));
                            if(ids.length!=kinds.length||ids.length!=orient.length||ids.length!=usage.length||ids.length!=mask.length)throw new IOException("Inconsistent FSPT arrays: "+type+"/"+rcid);
                            for(int i=0;i<ids.length;i++)if(kinds[i]==130) {
                                if(!edgeIds.contains(ids[i]))throw new IOException("Missing edge "+ids[i]+" for "+type+"/"+rcid);
                                link.setString(1,type);link.setInt(2,rcid);link.setInt(3,i);link.setInt(4,ids[i]);link.setInt(5,orient[i]);link.setInt(6,usage[i]);link.setInt(7,mask[i]);link.addBatch();
                            }
                        }
                    }feature.executeBatch();link.executeBatch();
                }
            }
            statement.execute("CREATE INDEX edge_owners ON links(edge)");
            try(var put=db.prepareStatement("INSERT INTO metadata VALUES(?,?)")){
                for(var e:Map.of("format",FORMAT,"revision",REVISION,"snapshot",identity).entrySet()){put.setString(1,e.getKey());put.setString(2,e.getValue());put.addBatch();}put.executeBatch();
            }
            db.commit();try(var rs=statement.executeQuery("PRAGMA quick_check")){if(!rs.next()||!rs.getString(1).equals("ok"))throw new IOException("Sidecar integrity failed");}
        }catch(SQLException|ParseException error){throw new IOException("Cannot prepare native edge metadata",error);}
    }
    /** Administrative prewarm; workers invoke separate GDAL processes, never JNI. */
    public static void main(String[] args) throws Exception {
        if(args.length==4 && args[0].equals("--cell")){Path source=Path.of(args[1]),snapshot=Path.of(args[2]);System.out.println(createLocked(source,snapshot,args[3],300));return;}
        if(args.length!=4)throw new IllegalArgumentException("Usage: EdgeCache catalogue.sqlite cache ogr2ogr workers");
        Path index=Path.of(args[0]),cache=Path.of(args[1]);String executable=args[2];int workers=Integer.parseInt(args[3]);if(workers<1||workers>16)throw new IllegalArgumentException("workers 1..16");
        var pool=Executors.newFixedThreadPool(workers);var tasks=new ArrayList<Callable<Boolean>>();
        Path versionLog=Files.createTempFile(cache,"edge-version-",".log");String version;
        try{version=GdalCache.run(List.of(executable,"--version"),versionLog,30);}finally{Files.deleteIfExists(versionLog);}
        try(var db=DriverManager.getConnection("jdbc:sqlite:"+index);var s=db.createStatement();var rs=s.executeQuery("SELECT path FROM cells ORDER BY name")) {
            while(rs.next()) {Path source=index.getParent().resolve(rs.getString(1));tasks.add(()->{
                Path snapshot=cache.resolve(GdalCache.fingerprint(source,version)+".gpkg");
                if(!Files.exists(snapshot))snapshot=GdalCache.materialize(source,cache,executable,300);
                if(Files.isRegularFile(target(snapshot)))return false;
                createLocked(source,snapshot,executable,300);return true;
            });}
        }
        var completion=new ExecutorCompletionService<Boolean>(pool);for(var task:tasks)completion.submit(task);
        int made=0,failed=0;long start=System.nanoTime();
        try{for(int i=1;i<=tasks.size();i++){try{if(completion.take().get())made++;}catch(ExecutionException e){failed++;e.getCause().printStackTrace();}
            if(i%100==0||i==tasks.size())System.out.printf(Locale.ROOT,"Validated %d/%d; created %d; failed %d; %.1fs%n",i,tasks.size(),made,failed,(System.nanoTime()-start)/1e9);
        }}finally{pool.shutdown();}
        if(failed>0)throw new IOException(failed+" sidecars failed");
    }
}
