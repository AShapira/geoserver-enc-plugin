package org.enc.geoserver;

import java.io.IOException;
import java.io.Serializable;
import java.nio.file.Path;
import java.util.*;
import org.geotools.api.data.*;
import org.geotools.api.feature.simple.*;
import org.geotools.api.feature.type.Name;
import org.geotools.api.filter.Filter;
import org.geotools.data.store.*;
import org.geotools.factory.CommonFactoryFinder;
import org.geotools.feature.simple.*;
import org.geotools.filter.visitor.ExtractBoundsFilterVisitor;
import org.geotools.geometry.jts.ReferencedEnvelope;
import org.geotools.geopkg.GeoPkgDataStoreFactory;
import org.geotools.referencing.crs.DefaultGeographicCRS;
import org.locationtech.jts.geom.*;
import org.locationtech.jts.operation.overlayng.OverlayNG;

/** One read-only store for an entire ENC catalogue, with bounded lazy cell readers. */
final class CatalogueDataStore extends ContentDataStore {
    private final CatalogueIndex index;
    private final Path cache;
    private final String executable;
    private final int timeout, poolSize;
    private final double safety;
    private final Map<String,SimpleFeatureType> schemas=new TreeMap<>();
    private final LinkedHashMap<String,Lease> pool=new LinkedHashMap<>(16,.75f,true);
    private boolean closed;
    private final Map<String,Path> snapshots=new HashMap<>();
    private static final class Lease {
        final DataStore store;int readers;
        Lease(DataStore store) { this.store=store; }
    }

    CatalogueDataStore(Path catalogue,Path cache,String executable,int timeout,int poolSize,double safety,String namespace) throws IOException {
        this.index=new CatalogueIndex(catalogue);this.cache=cache;this.executable=executable;
        this.timeout=timeout;this.poolSize=poolSize;this.safety=safety;
        setNamespaceURI(namespace);
        for(var entry:index.fields.entrySet()) {
            if(entry.getKey().equals("C_ASSO") || entry.getKey().equals("C_AGGR")) continue;
            SimpleFeatureTypeBuilder builder=new SimpleFeatureTypeBuilder();
            builder.setName(entry.getKey());if(namespace!=null) builder.setNamespaceURI(namespace);
            builder.setCRS(DefaultGeographicCRS.WGS84);builder.add("geom",Geometry.class);builder.setDefaultGeometry("geom");
            for(var field:entry.getValue()) {
                Class<?> binding=switch(field.type()) { case "Integer"->Integer.class;case "Integer64"->Long.class;case "Real"->Double.class;default->String.class; };
                builder.add(field.name(),binding);
            }
            builder.add("_enc_cell",String.class);builder.add("_enc_cscl",Integer.class);builder.add("_enc_safety_contour",Double.class);
            if(entry.getKey().equals("TOPMAR")) builder.add("_enc_floating",Integer.class);
            S57DataStore.addPortrayalFields(builder);
            schemas.put(entry.getKey(),builder.buildFeatureType());
        }
    }
    @Override protected List<Name> createTypeNames() { return schemas.values().stream().map(SimpleFeatureType::getName).toList(); }
    private synchronized Lease acquire(CatalogueIndex.Cell cell) throws IOException {
        if(closed) throw new IOException("ENC catalogue is disposed");
        Lease lease=pool.get(cell.name());
        if(lease==null) {
            Path snapshot=snapshots.get(cell.name());
            if(snapshot==null) { snapshot=GdalCache.materialize(cell.source(),cache,executable,timeout);snapshots.put(cell.name(),snapshot); }
            Map<String,Serializable> params=new HashMap<>();params.put("dbtype","geopkg");params.put("database",snapshot.toString());
            // Small pools per cell; total number of retained cell stores is bounded.
            params.put("max connections",2);params.put("min connections",0);
            Path metadata=EdgeCache.materialize(cell.source(),snapshot,executable,timeout);
            lease=new Lease(new S57DataStore(new GeoPkgDataStoreFactory().createDataStore(params),metadata,safety));pool.put(cell.name(),lease);
        }
        lease.readers++;evict();return lease;
    }
    private synchronized void release(Lease lease) { lease.readers--;evict(); }
    private void evict() {
        var iterator=pool.entrySet().iterator();
        while(iterator.hasNext() && (closed || pool.size()>poolSize)) {
            Lease lease=iterator.next().getValue();
            if(lease.readers==0) { lease.store.dispose();iterator.remove(); }
        }
    }
    @Override public synchronized void dispose() { closed=true;evict();super.dispose(); }
    private static double scale() {
        return RenderScale.value();
    }
    private Envelope viewport(Query query) {
        Object result=query.getFilter().accept(ExtractBoundsFilterVisitor.BOUNDS_VISITOR,null);
        if(result instanceof Envelope envelope && !envelope.isNull() && Double.isFinite(envelope.getMinX()) && Double.isFinite(envelope.getMaxX())) return envelope;
        return index.bounds;
    }
    @Override protected ContentFeatureSource createFeatureSource(ContentEntry entry) {
        return new ContentFeatureSource(entry,Query.ALL) {
            @Override protected SimpleFeatureType buildFeatureType() { return schemas.get(entry.getTypeName()); }
            @Override protected ReferencedEnvelope getBoundsInternal(Query query) {
                return new ReferencedEnvelope(index.bounds,DefaultGeographicCRS.WGS84);
            }
            @Override protected int getCountInternal(Query query) {
                if(query.getFilter()!=Filter.INCLUDE || scale()>0) return -1;
                long count=index.cells.stream().mapToLong(c->c.classes().getOrDefault(entry.getTypeName(),0L)).sum();
                return count>Integer.MAX_VALUE?-1:(int)count;
            }
            @Override protected boolean canFilter() { return true; }
            @Override protected FeatureReader<SimpleFeatureType,SimpleFeature> getReaderInternal(Query query) throws IOException {
                return new CatalogueReader(entry.getTypeName(),query);
            }
        };
    }

    private final class CatalogueReader implements FeatureReader<SimpleFeatureType,SimpleFeature> {
        final String type;
        final Query query;
        final Envelope bounds;
        final Iterator<CatalogueIndex.Selection> cells;
        final SimpleFeatureBuilder builder;
        FeatureReader<SimpleFeatureType,SimpleFeature> current;
        CatalogueIndex.Selection selection;
        Lease lease;
        SimpleFeature next;
        boolean finished;
        CatalogueReader(String type,Query query) {
            this.type=type;this.query=query;this.bounds=viewport(query);
            cells=index.select(bounds,scale()).stream().filter(s->s.cell().classes().getOrDefault(type,0L)>0).iterator();
            builder=new SimpleFeatureBuilder(schemas.get(type));
        }
        @Override public SimpleFeatureType getFeatureType() { return schemas.get(type); }
        void closeCell() throws IOException {
            try { if(current!=null) current.close(); }
            finally { current=null;if(lease!=null) release(lease);lease=null; }
        }
        @Override public boolean hasNext() throws IOException {
            if(next!=null) return true;
            if(finished) return false;
            try {
                while(true) {
                    if(current==null) {
                        if(!cells.hasNext()) {close();return false;}
                        selection=cells.next();lease=acquire(selection.cell());
                        var schema=lease.store.getSchema(type);
                        var filter=CommonFactoryFinder.getFilterFactory().bbox(schema.getGeometryDescriptor().getLocalName(),bounds.getMinX(),bounds.getMinY(),bounds.getMaxX(),bounds.getMaxY(),"EPSG:4326");
                        current=lease.store.getFeatureReader(new Query(type,filter),Transaction.AUTO_COMMIT);
                    }
                    while(current.hasNext()) {
                        SimpleFeature original=current.next();
                        Geometry geometry=(Geometry)original.getDefaultGeometry();
                        if(geometry==null || geometry.isEmpty()) continue;
                        if(selection.visible()!=null) {
                            if(!selection.preparedVisible().intersects(geometry)) continue;
                            if(geometry.getDimension()==0 && selection.preparedObscured()!=null && selection.preparedObscured().covers(geometry)) continue;
                            if(!selection.preparedVisible().covers(geometry)) geometry=CatalogueIndex.overlay(geometry,selection.visible(),OverlayNG.INTERSECTION);
                            if(geometry.isEmpty() || geometry.getDimension()!=((Geometry)original.getDefaultGeometry()).getDimension()) continue;
                        }
                        builder.reset();builder.set("geom",geometry);
                        for(var attribute:original.getProperties()) {
                            String name=attribute.getName().getLocalPart();
                            if(schemas.get(type).getDescriptor(name)!=null && !name.equals(original.getFeatureType().getGeometryDescriptor().getLocalName())) builder.set(name,attribute.getValue());
                        }
                        builder.set("_enc_cell",selection.cell().name());builder.set("_enc_cscl",selection.cell().scale());
                        double contour=selection.cell().safetyContour(safety);
                        builder.set("_enc_safety_contour",Double.isNaN(contour)?null:contour);
                        if(selection.visible()!=null) {
                            var clipped=new IdentityHashMap<Geometry,Geometry>();
                            for(String field:List.of("_enc_line","_enc_line_normal","_enc_line_quality")) {
                                Geometry line=(Geometry)original.getAttribute(field);
                                if(line!=null&&!line.isEmpty()) {
                                    Geometry value=clipped.get(line);
                                    if(value==null){value=selection.preparedVisible().covers(line)?line:CatalogueIndex.overlay(line,selection.visible(),OverlayNG.INTERSECTION);clipped.put(line,value);}
                                    builder.set(field,value);
                                }
                            }
                        }
                        SimpleFeature feature=builder.buildFeature(selection.cell().name()+"."+original.getID());
                        if(query.getFilter().evaluate(feature)) {next=feature;return true;}
                    }
                    closeCell();
                }
            } catch(IOException | RuntimeException e) {close();throw e;}
        }
        @Override public SimpleFeature next() throws IOException {
            if(!hasNext()) throw new NoSuchElementException();
            SimpleFeature result=next;next=null;return result;
        }
        @Override public void close() throws IOException { finished=true;next=null;closeCell(); }
    }
}
