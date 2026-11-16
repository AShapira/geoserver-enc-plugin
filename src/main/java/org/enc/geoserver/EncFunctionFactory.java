package org.enc.geoserver;

import java.util.*;
import java.util.regex.Pattern;
import org.geotools.api.feature.type.Name;
import org.geotools.api.filter.capability.FunctionName;
import org.geotools.api.filter.expression.*;
import org.geotools.filter.FunctionExpressionImpl;
import org.geotools.filter.FunctionFactory;
import org.geotools.filter.capability.FunctionNameImpl;

/** Attribute-based text procedures shared by generated SLDs. */
public final class EncFunctionFactory implements FunctionFactory {
    private static final List<FunctionName> NAMES=List.of(new FunctionNameImpl("encFormat",-1),new FunctionNameImpl("encLightDescription",8));
    @Override public List<FunctionName> getFunctionNames() {return NAMES;}
    @Override public Function function(Name name,List<Expression> args,Literal fallback) {return function(name.getLocalPart(),args,fallback);}
    @Override public Function function(String name,List<Expression> args,Literal fallback) {
        if(NAMES.stream().noneMatch(n->n.getName().equals(name))) return null;
        var function=new FunctionExpressionImpl(name) {
            @Override public Object evaluate(Object feature) {
                List<Object> values=params.stream().map(p->p.evaluate(feature)).toList();
                return name.equals("encFormat")?format(values):lightDescription(values);
            }
        };
        function.setParameters(args);function.setFallbackValue(fallback);return function;
    }
    static String text(Object o) {return o==null?"":o.toString();}
    static double number(Object o) {try {return Double.parseDouble(text(o));}catch(NumberFormatException ignored){return Double.NaN;}}
    static String decimal(Object o) {double d=number(o);return !Double.isFinite(d)?"":d==Math.rint(d)?Long.toString((long)d):String.format(Locale.ROOT,"%.1f",d);}
    static String format(List<Object> values) {
        if(values.isEmpty()) return "";
        String format=text(values.get(0)).replaceAll("%([^%]*?)l([fdi])","%$1$2");
        var matcher=Pattern.compile("%(?:[-+ #0]*[0-9]*)(?:\\.[0-9]+)?([dfs])").matcher(format);
        List<Object> args=new ArrayList<>();int index=1;
        while(matcher.find()) {
            if(index>=values.size() || values.get(index)==null || text(values.get(index)).isEmpty()) return "";
            Object value=values.get(index++);
            if(matcher.group(1).equals("s")) args.add(text(value));
            else {double d=number(value);if(!Double.isFinite(d)) return "";args.add(matcher.group(1).equals("d")?(Object)(long)d:d);}
        }
        try {return String.format(Locale.ROOT,format,args.toArray()).trim();}catch(IllegalFormatException error){return "";}
    }
    static String lightDescription(List<Object> a) {
        if(a.size()!=8) return "";
        String[] names={"","F","Fl","LFl","Q","VQ","UQ","Iso","Occ","IQ","IVQ","IUQ","Mo","F + Fl","Fl + LFl","Occ + Fl","F + LFl","Al Occ","Al LFl","Al Fl","Al Grp","F","F","F","F","Q + LFl","VQ + LFl","UQ + LFl","Alt","F + Alt"};
        int code=(int)number(a.get(0));StringBuilder s=new StringBuilder(code>0&&code<names.length?names[code]:"");
        String group=text(a.get(1));if(!group.isEmpty()&&!group.equals("(1)")) s.append(group);
        if(!Double.isFinite(number(a.get(6)))) {
            StringBuilder colors=new StringBuilder();
            for(String token:text(a.get(2)).split(",")) colors.append(switch(token.trim()){case "1"->"W";case "3"->"R";case "4"->"G";case "6","9","11"->"Y";default->"";});
            if(!colors.isEmpty()) s.append(' ').append(colors);
        }
        for(int i=3;i<=5;i++) {String value=decimal(a.get(i));if(!value.isEmpty())s.append(' ').append(value).append(i==3?"s":i==4?"m":"Nm");}
        if(code==21||code==23)s.append(" (vert)");if(code==22||code==24)s.append(" (horz)");
        return s.toString().trim();
    }
}
