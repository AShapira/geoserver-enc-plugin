package org.enc.geoserver;

import java.io.IOException;
import java.util.*;
import org.geotools.api.data.*;
import org.locationtech.jts.geom.*;

/** Per-cell, lazily read parent positions; never modifies the GDAL snapshot. */
final class AtonContext {
    private final Set<String> floating=new HashSet<>();
    static String key(Coordinate c) {return Math.round(c.x*1e7)+":"+Math.round(c.y*1e7);}
    AtonContext(DataStore store) throws IOException {
        for(String type:store.getTypeNames()) if(type.startsWith("BOY") || type.equals("LITFLT") || type.equals("LITVES")) {
            try(var reader=store.getFeatureReader(new Query(type),Transaction.AUTO_COMMIT)) {
                while(reader.hasNext()) {
                    Object value=reader.next().getDefaultGeometry();
                    if(value instanceof Geometry geometry && !geometry.isEmpty() && geometry.getDimension()==0)
                        for(Coordinate c:geometry.getCoordinates()) floating.add(key(c));
                }
            }
        }
    }
    int floating(Geometry geometry) {
        return geometry!=null && !geometry.isEmpty() && floating.contains(key(geometry.getCoordinate()))?1:0;
    }
}
