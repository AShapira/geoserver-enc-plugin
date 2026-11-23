package org.enc.geoserver;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.geotools.feature.simple.SimpleFeatureBuilder;
import org.geotools.feature.simple.SimpleFeatureTypeBuilder;
import org.locationtech.jts.geom.Geometry;

/** Field contract used by the chart-independent SLD compiler. */
final class PortrayalSchema {
    record Depths(double shallow, double safety, double deep) {
        Depths {
            if (!Double.isFinite(shallow) || !Double.isFinite(safety) || !Double.isFinite(deep)
                    || shallow < 0 || shallow > safety || safety > deep)
                throw new IllegalArgumentException("Require finite depths with 0 <= shallow <= safety <= deep");
        }
        void set(SimpleFeatureBuilder builder) {
            builder.set("_enc_shallow_depth", shallow);
            builder.set("_enc_safety_depth", safety);
            builder.set("_enc_deep_depth", deep);
        }
    }
    private static final Map<String,Map<String,Class<?>>> fields = load();
    private static Map<String,Map<String,Class<?>>> load() {
        var result = new HashMap<String,Map<String,Class<?>>>();
        try (var input = PortrayalSchema.class.getResourceAsStream("portrayal-schema.tsv");
             var reader = new BufferedReader(new InputStreamReader(Objects.requireNonNull(input), StandardCharsets.UTF_8))) {
            for (String line; (line = reader.readLine()) != null;) {
                var parts = line.split("\t");
                Class<?> binding = switch(parts[2]) {
                    case "Integer" -> Integer.class;
                    case "Real" -> Double.class;
                    case "Geometry" -> Geometry.class;
                    case "String" -> String.class;
                    default -> throw new IOException("Unknown portrayal field type: "+parts[2]);
                };
                result.computeIfAbsent(parts[0], key -> new LinkedHashMap<>()).put(parts[1], binding);
            }
        } catch (IOException e) { throw new UncheckedIOException(e); }
        return result;
    }
    static void extend(String type, SimpleFeatureTypeBuilder builder) {
        fields.getOrDefault(type,Map.of()).forEach((name,binding) -> {
            if (builder.get(name) == null) builder.add(name,binding);
        });
    }
    static boolean supports(String type) { return fields.containsKey(type); }
}
