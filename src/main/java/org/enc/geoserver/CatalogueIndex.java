package org.enc.geoserver;

import java.io.IOException;
import java.nio.file.Path;
import java.sql.*;
import java.util.*;
import org.locationtech.jts.geom.*;
import org.locationtech.jts.geom.prep.PreparedGeometry;
import org.locationtech.jts.geom.prep.PreparedGeometryFactory;
import org.locationtech.jts.io.WKBReader;
import org.locationtech.jts.index.strtree.STRtree;
import org.locationtech.jts.operation.overlayng.OverlayNG;
import org.locationtech.jts.operation.overlayng.OverlayNGRobust;

/** Immutable national inventory; no native datasets are opened to discover schemas. */
final class CatalogueIndex {
    record Field(String name, String type) {}
    record Cell(String name, Path source, int scale, int band, Geometry coverage,
                Map<String,Long> classes, double[] contours) {
        double safetyContour(double requested) {
            return Arrays.stream(contours).filter(d->d>=requested).min().orElse(Double.NaN);
        }
    }
    record Selection(Cell cell, Geometry visible, Geometry obscured,
                     PreparedGeometry preparedVisible, PreparedGeometry preparedObscured) {
        Selection(Cell cell, Geometry visible, Geometry obscured) {
            this(cell,visible,obscured,visible==null?null:PreparedGeometryFactory.prepare(visible),
                obscured==null?null:PreparedGeometryFactory.prepare(obscured));
        }
    }
    final List<Cell> cells=new ArrayList<>();
    final Map<String,List<Field>> fields=new TreeMap<>();
    final STRtree tree=new STRtree();
    final Envelope bounds=new Envelope();
    private final Map<String,List<Selection>> selections=Collections.synchronizedMap(
        new LinkedHashMap<>(16,.75f,true) {
            // The chart has more than 24 distinct symbol-buffer extents per view.
            // Retain enough quilts to avoid rebuilding them for every style pass.
            @Override protected boolean removeEldestEntry(Map.Entry<String,List<Selection>> entry) { return size()>128; }
        });

    CatalogueIndex(Path index) throws IOException {
        Path root=index.toRealPath().getParent();
        try(var db=DriverManager.getConnection("jdbc:sqlite:"+index.toAbsolutePath());var statement=db.createStatement()) {
            try(var rows=statement.executeQuery("SELECT value FROM metadata WHERE key='format'")) {
                if(!rows.next() || !"enc-catalogue-1".equals(rows.getString(1))) throw new IOException("Unsupported ENC catalogue format");
            }
            Map<String,Map<String,Long>> counts=new HashMap<>();
            try(var rows=statement.executeQuery("SELECT cell,class,features FROM cell_classes")) {
                while(rows.next()) counts.computeIfAbsent(rows.getString(1),k->new HashMap<>()).put(rows.getString(2),rows.getLong(3));
            }
            try(var rows=statement.executeQuery("SELECT class,name,type FROM fields ORDER BY class,ordinal")) {
                while(rows.next()) fields.computeIfAbsent(rows.getString(1),k->new ArrayList<>()).add(new Field(rows.getString(2),rows.getString(3)));
            }
            WKBReader reader=new WKBReader();
            try(var rows=statement.executeQuery("SELECT name,path,cscale,band,coverage,contours FROM cells ORDER BY name")) {
                while(rows.next()) {
                    Path source=root.resolve(rows.getString(2)).normalize();
                    if(!source.startsWith(root)) throw new IOException("Cell path escapes catalogue directory");
                    Geometry coverage=reader.read(rows.getBytes(5));
                    String contourText=rows.getString(6);
                    double[] contours=contourText==null || contourText.isBlank()?new double[0]:Arrays.stream(contourText.split(",")).mapToDouble(Double::parseDouble).toArray();
                    Cell cell=new Cell(rows.getString(1),source,rows.getInt(3),rows.getInt(4),coverage,
                        Map.copyOf(counts.getOrDefault(rows.getString(1),Map.of())),contours);
                    cells.add(cell);
                    if(coverage.isEmpty()) continue;
                    bounds.expandToInclude(coverage.getEnvelopeInternal());
                    for(int i=0;i<coverage.getNumGeometries();i++) tree.insert(coverage.getGeometryN(i).getEnvelopeInternal(),cell);
                }
            }
            if(cells.isEmpty()) throw new IOException("ENC catalogue is empty");
            tree.build();
        } catch(SQLException | org.locationtech.jts.io.ParseException | NumberFormatException error) {
            throw new IOException("Cannot read ENC catalogue "+index,error);
        }
    }

    static Geometry overlay(Geometry a, Geometry b, int operation) {
        return OverlayNGRobust.overlay(a,b,operation);
    }

    /** More detailed eligible coverage masks all coarser classes, even if a class is absent. */
    static List<Selection> quilt(Collection<Cell> candidates, Envelope viewport, double scale) {
        Geometry window=new GeometryFactory().toGeometry(viewport);
        List<Cell> ordered=candidates.stream().filter(c->c.band()==1 || scale<=c.scale()*4d)
            .sorted(Comparator.comparingInt(Cell::scale).thenComparing(Comparator.comparingInt(Cell::band).reversed()).thenComparing(Cell::name)).toList();
        Geometry covered=null;
        List<Selection> result=new ArrayList<>();
        for(Cell cell:ordered) {
            if(!cell.coverage().intersects(window)) continue;
            Geometry area=overlay(cell.coverage(),window,OverlayNG.INTERSECTION);
            boolean overlay=cell.band()==99;
            Geometry visible=overlay||covered==null?area:overlay(area,covered,OverlayNG.DIFFERENCE);
            if(visible.isEmpty() || visible.getDimension()<2 || visible.getArea()==0) continue;
            result.add(new Selection(cell,visible,overlay?null:covered));
            if(!overlay) covered=covered==null?area:overlay(covered,area,OverlayNG.UNION);
        }
        return List.copyOf(result);
    }

    List<Selection> select(Envelope viewport, double scale) {
        if(viewport==null) viewport=bounds;
        String key=viewport.toString()+":"+Double.toString(scale);
        List<Selection> existing=selections.get(key);
        if(existing!=null) return existing;
        @SuppressWarnings("unchecked") List<Cell> hits=tree.query(viewport);
        Set<Cell> candidates=new LinkedHashSet<>(hits);
        List<Selection> result;
        if(scale>0 && Double.isFinite(scale)) result=quilt(candidates,viewport,scale);
        else result=candidates.stream().sorted(Comparator.comparing(Cell::name)).map(c->new Selection(c,null,null)).toList();
        java.util.logging.Logger.getLogger(CatalogueIndex.class.getName()).fine("ENC select scale="+scale+" bbox="+viewport+" candidates="+candidates.size()+" selected="+result.size());
        selections.put(key,result);return result;
    }
}
