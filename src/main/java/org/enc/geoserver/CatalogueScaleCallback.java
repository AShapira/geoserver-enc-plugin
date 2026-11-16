package org.enc.geoserver;

import org.geoserver.wms.GetMapCallbackAdapter;
import org.geoserver.wms.GetMapRequest;
import org.geoserver.wms.WebMap;
import org.geoserver.wms.WMSMapContent;
import org.geotools.geometry.jts.ReferencedEnvelope;
import org.geotools.referencing.CRS;
import org.geotools.filter.function.EnvFunction;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;

/** GeoServer does not expose the style rendering environment in datastore queries. */
public final class CatalogueScaleCallback extends GetMapCallbackAdapter {
    private static final int LIMIT=Math.max(1,Integer.getInteger("enc.maxConcurrentRenders",4));
    private static final Semaphore RENDERS=new Semaphore(LIMIT,true);
    private static final ThreadLocal<Boolean> PERMIT=new ThreadLocal<>();
    @Override public GetMapRequest initRequest(GetMapRequest request) {
        clear();return request;
    }
    @Override public WMSMapContent beforeRender(WMSMapContent content) {
        boolean enc=content.layers().stream().anyMatch(l->l.getFeatureSource()!=null && l.getFeatureSource().getSchema().getDescriptor("_enc_lookup")!=null);
        if(enc) acquire();
        RenderScale.CURRENT.set(renderingScale(content));
        // ENC styles use the same normalized scale, without changing other WMS styles.
        EnvFunction.setLocalValue("enc_scale_denominator",RenderScale.CURRENT.get());
        return content;
    }
    static double renderingScale(WMSMapContent content) {
        var crs=content.getCoordinateReferenceSystem();
        if(crs==null || CRS.getAxisOrder(crs)!=CRS.AxisOrder.NORTH_EAST) return content.getScaleDenominator(true);
        // beforeRender precedes GeoServer's normalization of north/east WMS 1.3 axes.
        // Compute on an east/north copy, without changing the request or its viewport.
        var normalized=new WMSMapContent(content.getRequest());
        try {
            var bounds=content.getViewport().getBounds();
            // toSRS may return an axis-strict URN under GeoServer's forceXY setting;
            // such URNs override decode(..., true). Use the authority identifier.
            var eastFirst=CRS.decode(CRS.lookupIdentifier(crs,true),true);
            normalized.getViewport().setBounds(new ReferencedEnvelope(bounds.getMinY(),bounds.getMaxY(),bounds.getMinX(),bounds.getMaxX(),eastFirst));
            normalized.setMapWidth(content.getMapWidth());normalized.setMapHeight(content.getMapHeight());
            normalized.setAngle(content.getAngle());
            return normalized.getScaleDenominator(true);
        } catch(org.geotools.api.referencing.FactoryException error) {
            throw new IllegalArgumentException("Cannot normalize ENC rendering axes",error);
        } finally { normalized.dispose(); }
    }
    private static void clear() {
        if(Boolean.TRUE.equals(PERMIT.get())){PERMIT.remove();RENDERS.release();}
        RenderScale.CURRENT.remove();EnvFunction.setLocalValue("enc_scale_denominator",null);
    }
    static void acquire() {
        if(Boolean.TRUE.equals(PERMIT.get()))return;
        try {
            if(!RENDERS.tryAcquire(30,TimeUnit.SECONDS))throw new IllegalStateException("ENC render queue timed out after 30 seconds");
            PERMIT.set(true);
        }catch(InterruptedException e){Thread.currentThread().interrupt();throw new IllegalStateException("ENC render interrupted",e);}
    }
    static int availablePermits(){return RENDERS.availablePermits();}
    @Override public WebMap finished(WebMap map) { clear();return map; }
    @Override public void failed(Throwable error) { clear(); }
}
