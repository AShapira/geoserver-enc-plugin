package org.enc.geoserver;

import java.util.*;
import java.util.regex.Pattern;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Element;

/** The same ordered Plain/Lines/Simplified lookup selection as the SLD compiler. */
final class S52Lookup {
    record Rule(int id,int priority,boolean base,boolean line,List<String> attributes,String instruction) {
        int priority(Map<String,Object> attributes) {
            if(instruction.contains("CS(RESARE02)"))
                for(int restriction:EdgeCache.integers(attributes.get("RESTRN")))
                    if(restriction>=1&&restriction<=8||restriction==14)return 6;
            return priority;
        }
        boolean contour(){return instruction.contains("CS(DEPCNT02)");}
    }
    final Map<String,List<Rule>> rules=new HashMap<>();
    static final S52Lookup INSTANCE=new S52Lookup();
    private S52Lookup() {
        try {
            var f=DocumentBuilderFactory.newInstance();f.setFeature("http://apache.org/xml/features/disallow-doctype-decl",true);
            var xml=f.newDocumentBuilder().parse(getClass().getResourceAsStream("s52/chartsymbols.xml"));
            var list=xml.getElementsByTagName("lookup");
            var priorities=List.of("No data","Group 1","Area 1","Area 2","Point Symbol","Line Symbol","Area Symbol","Routing","Hazards","Mariners");
            for(int i=0;i<list.getLength();i++) {
                Element e=(Element)list.item(i);String table=text(e,"table-name"),kind=text(e,"type");
                if(!Set.of("Plain","Lines","Simplified").contains(table))continue;
                int prim=switch(kind){case "Point"->1;case "Line"->2;case "Area"->3;default->0;};
                String instruction=text(e,"instruction");
                boolean line=drawsLine(e.getAttribute("name"),prim,instruction);
                List<String> attributes=new ArrayList<>();var a=e.getElementsByTagName("attrib-code");
                for(int j=0;j<a.getLength();j++)attributes.add(a.item(j).getTextContent());
                int priority=priorities.indexOf(text(e,"disp-prio"));
                rules.computeIfAbsent(e.getAttribute("name")+":"+prim,k->new ArrayList<>()).add(new Rule(Integer.parseInt(e.getAttribute("RCID")),priority<0?5:priority,text(e,"display-cat").equals("Displaybase"),line,List.copyOf(attributes),instruction));
            }
            for(var value:rules.values())value.sort(Comparator.comparingInt((Rule r)->r.attributes().size()).reversed());
        } catch(Exception error){throw new ExceptionInInitializerError(error);}
    }
    private static String text(Element e,String tag){var nodes=e.getElementsByTagName(tag);return nodes.getLength()==0?"":nodes.item(0).getTextContent();}
    static boolean drawsLine(String type,int primitive,String instruction) {
        if(primitive==1)return false;
        if(Pattern.compile("(?:LS|LC)\\(").matcher(instruction).find())return true;
        var conditional=Pattern.compile("CS\\(([^)]+)\\)").matcher(instruction);
        while(conditional.find()) {
            String command=conditional.group(1);
            // Keep this aligned with Compiler.conditional, including its explicit fallback.
            if(command.equals("DEPARE01")){if(primitive!=3||type.equals("DRGARE"))return true;}
            else if(command.startsWith("RESTRN")||command.startsWith("SOUNDG")||command.startsWith("LIGHTS")||command.startsWith("TOPMAR"))continue;
            else return true;
        }
        return false;
    }
    Rule select(String type,int prim,Map<String,Object> attributes) {
        for(Rule r:rules.getOrDefault(type+":"+prim,List.of()))if(r.attributes().stream().allMatch(c->matches(c,attributes)))return r;
        return null;
    }
    static boolean matches(String code,Map<String,Object> attributes) {
        String name=code.substring(0,6),expected=code.substring(6);Object actual=attributes.get(name);
        if(expected.equals("?"))return actual==null;
        if(actual==null)return false;
        if(expected.isBlank())return true;
        if(actual instanceof Number number){try{return number.doubleValue()==Double.parseDouble(expected);}catch(NumberFormatException error){return false;}}
        if(expected.contains(","))return actual.toString().equals(expected);
        return Arrays.asList(actual.toString().split(",")).contains(expected);
    }
}
