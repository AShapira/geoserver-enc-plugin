package org.enc.geoserver;

/** Request-scoped rendering scale, also used for GeoWebCache's internal WMS renders. */
final class RenderScale {
    static final ThreadLocal<Double> CURRENT=new ThreadLocal<>();
    static double value() {
        Double rendering=CURRENT.get();if(rendering!=null)return rendering;
        Object value=org.geotools.filter.function.EnvFunction.getLocalValues().get("WMS_SCALE_DENOMINATOR");
        return value instanceof Number number?number.doubleValue():0;
    }
    private RenderScale() {}
}
