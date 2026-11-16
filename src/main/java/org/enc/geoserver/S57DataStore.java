package org.enc.geoserver;

import java.io.IOException;
import java.util.*;
import org.geotools.api.data.*;
import org.geotools.api.feature.simple.*;
import org.geotools.api.feature.type.Name;
import org.geotools.data.store.*;
import org.geotools.geometry.jts.ReferencedEnvelope;
import org.geotools.feature.simple.*;
import org.locationtech.jts.geom.Geometry;
import org.locationtech.jts.geom.Envelope;
import org.geotools.api.filter.Filter;
import org.geotools.filter.visitor.ExtractBoundsFilterVisitor;
import org.geotools.factory.CommonFactoryFinder;
import java.nio.file.Path;

/** Only ContentFeatureSource is exposed, never the writable GeoPackage feature store. */
final class S57DataStore extends ContentDataStore {
    private final DataStore delegate;
    private AtonContext context;
    private final Path metadataFile;
    private EdgeContext metadata;
    private synchronized EdgeContext metadata() throws IOException {
        if(metadata==null&&metadataFile!=null)metadata=new EdgeContext(metadataFile);
        return metadata;
    }
    private synchronized AtonContext context() throws IOException {
        if(context==null) context=new AtonContext(delegate);
        return context;
    }
    S57DataStore(DataStore delegate) { this(delegate,null); }
    S57DataStore(DataStore delegate,Path metadataFile) { this.delegate = Objects.requireNonNull(delegate);this.metadataFile=metadataFile; }

    @Override protected List<Name> createTypeNames() throws IOException {
        List<Name> names = new ArrayList<>();
        for (Name name : delegate.getNames()) {
            if (delegate.getSchema(name).getGeometryDescriptor() != null) names.add(name);
        }
        return names;
    }
    @Override protected ContentFeatureSource createFeatureSource(ContentEntry entry) {
        boolean topmark=entry.getTypeName().equals("TOPMAR");
        boolean boundary=metadataFile!=null;
        boolean enriched=topmark||boundary;
        return new ContentFeatureSource(entry, Query.ALL) {
            @Override protected SimpleFeatureType buildFeatureType() throws IOException {
                var schema=delegate.getSchema(entry.getTypeName());
                if(!enriched) return schema;
                var builder=new SimpleFeatureTypeBuilder();builder.init(schema);
                if(topmark) builder.add("_enc_floating",Integer.class);
                if(boundary){builder.add("_enc_line",Geometry.class,schema.getCoordinateReferenceSystem());builder.add("_enc_lookup",Integer.class);}
                return builder.buildFeatureType();
            }
            @Override protected ReferencedEnvelope getBoundsInternal(Query query) throws IOException {
                return query.getFilter()==Filter.INCLUDE?delegate.getFeatureSource(entry.getTypeName()).getBounds():null;
            }
            @Override protected int getCountInternal(Query query) throws IOException {
                return query.getFilter()==Filter.INCLUDE?delegate.getFeatureSource(entry.getTypeName()).getCount(Query.ALL):-1;
            }
            @Override protected FeatureReader<SimpleFeatureType, SimpleFeature> getReaderInternal(Query query) throws IOException {
                if(!enriched) return delegate.getFeatureReader(query, Transaction.AUTO_COMMIT);
                AtonContext parents=topmark?context():null; // Close context readers before acquiring another connection.
                EdgeContext edges=boundary?metadata():null;
                var nativeSchema=delegate.getSchema(entry.getTypeName());
                Filter pushed=Filter.INCLUDE;
                Object extracted=query.getFilter().accept(ExtractBoundsFilterVisitor.BOUNDS_VISITOR,null);
                if(extracted instanceof Envelope b && !b.isNull() && Double.isFinite(b.getMinX()) && Double.isFinite(b.getMaxX()))
                    pushed=CommonFactoryFinder.getFilterFactory().bbox(nativeSchema.getGeometryDescriptor().getLocalName(),b.getMinX(),b.getMinY(),b.getMaxX(),b.getMaxY(),"EPSG:4326");
                var nativeReader=delegate.getFeatureReader(new Query(entry.getTypeName(),pushed),Transaction.AUTO_COMMIT);
                var schema=getSchema();var builder=new SimpleFeatureBuilder(schema);
                double scale=RenderScale.value();
                return new FeatureReader<SimpleFeatureType,SimpleFeature>() {
                    SimpleFeature next;
                    public SimpleFeatureType getFeatureType() {return schema;}
                    public boolean hasNext() throws IOException {
                      while(next==null&&nativeReader.hasNext()) {
                        var original=nativeReader.next();builder.reset();
                        for(var p:original.getProperties()) builder.set(p.getName().getLocalPart(),p.getValue());
                        if(topmark) builder.set("_enc_floating",parents.floating((Geometry)original.getDefaultGeometry()));
                        if(boundary){
                            int rcid=((Number)original.getAttribute("RCID")).intValue();
                            builder.set("_enc_lookup",edges.lookup(entry.getTypeName(),rcid));
                            builder.set("_enc_line",edges.line(entry.getTypeName(),rcid,scale,(Geometry)original.getDefaultGeometry()));
                        }
                        var f=builder.buildFeature(original.getID());if(query.getFilter().evaluate(f))next=f;
                      }
                      return next!=null;
                    }
                    public SimpleFeature next() throws IOException {if(!hasNext())throw new NoSuchElementException();var f=next;next=null;return f;}
                    public void close() throws IOException {nativeReader.close();}
                };
            }
            @Override protected boolean canFilter() { return true; }
            @Override protected boolean canSort() { return !enriched; }
            @Override protected boolean canLimit() { return !enriched; }
            @Override protected boolean canOffset() { return !enriched; }
            @Override protected boolean canRetype() { return !enriched; }
        };
    }
    @Override public void dispose() { super.dispose(); delegate.dispose(); }
}
