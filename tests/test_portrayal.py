import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from portrayal import Compiler, ROOT, attribute_filter, generate
from hpgl import render


def evaluate(e, properties):
    tag=e.tag.split('}')[-1]
    children=list(e)
    if tag=='PropertyName': return properties.get(e.text)
    if tag=='Literal':
        if e.text.lower() in ('true','false'): return e.text.lower()=='true'
        try: return float(e.text)
        except ValueError: return e.text
    if tag=='PropertyIsNull': return evaluate(e[0],properties) is None
    if tag=='Not': return not evaluate(e[0],properties)
    if tag=='And': return all(evaluate(c,properties) for c in children)
    if tag=='Or': return any(evaluate(c,properties) for c in children)
    if tag=='Function':
        if e.get('name')=='env': return properties.get('_scale',10000)
        if e.get('name')=='strMatches':
            value=evaluate(e[0],properties)
            return value is not None and re.fullmatch(evaluate(e[1],properties),str(value)) is not None
    if tag.startswith('PropertyIs'):
        a,b=(evaluate(c,properties) for c in children)
        if a is None or b is None: return False
        return {'PropertyIsEqualTo':lambda:a==b,'PropertyIsGreaterThanOrEqualTo':lambda:a>=b,
                'PropertyIsLessThan':lambda:a<b,'PropertyIsLessThanOrEqualTo':lambda:a<=b}[tag]()
    raise AssertionError(tag)


class PortrayalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.compiler=Compiler(ROOT/'portrayal/upstream',Path(self.temp.name))

    def test_list_membership_is_not_a_substring(self):
        f=attribute_filter('STATUS1',{'STATUS':'String'})
        for value,result in [(None,False),('11',False),('1',True),('2,1,7',True),('',False)]:
            self.assertEqual(result,evaluate(f,{'STATUS':value}))
        f=attribute_filter('COLOUR3,4,3',{'COLOUR':'String'})
        self.assertTrue(evaluate(f,{'COLOUR':'3,4,3'}))
        self.assertFalse(evaluate(f,{'COLOUR':'4,3,4'}))

    def test_buoy_lookup_is_exclusive_and_has_fallback(self):
        groups=self.compiler.compile('BOYLAT',{'PRIM':'Integer','BOYSHP':'Integer','CATLAM':'Integer','COLOUR':'String','SCAMIN':'Integer','OBJNAM':'String'})
        for attrs in [{'BOYSHP':1,'COLOUR':'3'},{'BOYSHP':2,'COLOUR':'4'},{'COLOUR':None},{'BOYSHP':99,'COLOUR':'99'}]:
            matches=[r for rules in groups.values() for r in rules if evaluate(r.find('{http://www.opengis.net/ogc}Filter')[0],{'PRIM':1,**attrs})]
            self.assertEqual(1,len(matches),attrs)
        # Scale-dependent aids disappear when zoomed out beyond SCAMIN.
        attrs={'PRIM':1,'BOYSHP':1,'COLOUR':'3','SCAMIN':22000,'_scale':50000}
        self.assertFalse(any(evaluate(r.find('{http://www.opengis.net/ogc}Filter')[0],attrs) for rules in groups.values() for r in rules))

    def test_depth_boundaries_are_exclusive_and_unknown_is_no_data(self):
        variants=self.compiler.conditional('DEPARE01','DEPARE','Area',{'DRVAL1':'Real'})
        for depth in [None,-1,0,1.99,2,4.99,5,10,100]:
            matches=[symbols for condition,symbols in variants if evaluate(condition,{'DRVAL1':depth})]
            self.assertEqual(1,len(matches),depth)
        unknown=[symbols for condition,symbols in variants if evaluate(condition,{'DRVAL1':None})][0]
        self.assertIn(self.compiler.color('NODTA'),ET.tostring(unknown[0],encoding='unicode'))

    def test_safety_contour_rounds_to_available_deeper_contour(self):
        from osgeo import ogr,osr
        ogr.UseExceptions();path=Path(self.temp.name)/'test.gpkg'
        ds=ogr.GetDriverByName('GPKG').CreateDataSource(str(path));srs=osr.SpatialReference();srs.ImportFromEPSG(4326)
        l=ds.CreateLayer('DEPCNT',srs,ogr.wkbLineString)
        for name,typ in [('VALDCO',ogr.OFTReal),('PRIM',ogr.OFTInteger)]: l.CreateField(ogr.FieldDefn(name,typ))
        for depth in [2,10,20]:
            f=ogr.Feature(l.GetLayerDefn());f.SetField('VALDCO',depth);f.SetField('PRIM',2);f.SetGeometry(ogr.CreateGeometryFromWkt('LINESTRING (0 0,1 1)'));l.CreateFeature(f)
        l=ds.CreateLayer('M_COVR',srs,ogr.wkbPolygon);f=ogr.Feature(l.GetLayerDefn());f.SetGeometry(ogr.CreateGeometryFromWkt('POLYGON ((0 0,1 0,1 1,0 0))'));l.CreateFeature(f)
        ds=None
        m=generate(path,Path(self.temp.name)/'styles',safety=5)
        self.assertEqual(10,m['safety_contour'])

    def test_all_pinned_complex_lines_and_patterns_render(self):
        for name,element in {**self.compiler.lines,**self.compiler.patterns}.items():
            with self.subTest(name=name):
                if element.find('vector') is not None:
                    image=render(element,self.compiler.colors,pattern=name in self.compiler.patterns)
                    self.assertIsNotNone(image.getbbox())
                graphic=self.compiler.vector_graphic(name,'pattern' if name in self.compiler.patterns else 'line')
                self.assertIsNotNone(graphic)

    def test_non_metre_depth_units_are_rejected(self):
        from osgeo import ogr
        ogr.UseExceptions()
        path=Path(self.temp.name)/'feet.gpkg'
        ds=ogr.GetDriverByName('GPKG').CreateDataSource(str(path))
        layer=ds.CreateLayer('DSID',geom_type=ogr.wkbNone)
        layer.CreateField(ogr.FieldDefn('DSPM_DUNI',ogr.OFTInteger))
        feature=ogr.Feature(layer.GetLayerDefn());feature.SetField('DSPM_DUNI',2)
        layer.CreateFeature(feature);ds=None
        with self.assertRaisesRegex(ValueError,'metre depth units'):
            generate(path,Path(self.temp.name)/'out')

    def test_palette_changes_symbol_pixels(self):
        self.compiler.symbol('BOYLAT14')
        night=Compiler(ROOT/'portrayal/upstream',Path(self.temp.name),'night');night.symbol('BOYLAT14')
        self.assertNotEqual((Path(self.temp.name)/'symbols/day_BOYLAT14.png').read_bytes(),(Path(self.temp.name)/'symbols/night_BOYLAT14.png').read_bytes())

    def test_ordinary_restricted_objects_do_not_invent_boundary_lines(self):
        variants=self.compiler.conditional('RESTRN01','SEAARE','Area',{'RESTRN':'String'})
        xml=ET.tostring(variants[0][1][0],encoding='unicode')
        self.assertIn('restriction?',xml)
        self.assertNotIn('LineSymbolizer',xml)
        self.assertEqual(2,len(self.compiler.conditional('RESARE02','RESARE','Area',{'RESTRN':'String'})[0][1]))

    def test_formatted_text_retains_units_colour_and_placement(self):
        variants=self.compiler.instructions("TE('Clr %3.1lf m','VERCLR',3,1,2,'15110',1,-1,CHBLK,23)",'BRIDGE','Area',{'VERCLR':'Real'})
        xml=ET.tostring(variants[0][1][0],encoding='unicode')
        self.assertIn('encFormat',xml);self.assertIn('Clr %3.1lf m',xml)
        self.assertIn('AnchorPointX>0<',xml);self.assertIn('font-size">16.0<',xml)

    def test_native_graphics_only_reference_present_fields(self):
        symbols=self.compiler.conditional('LIGHTS05','LIGHTS','Point',{'COLOUR':'String'})[0][1]
        xml=''.join(ET.tostring(s,encoding='unicode') for s in symbols)
        self.assertIn('${COLOUR}',xml);self.assertNotIn('${SECTR1}',xml)
        self.assertIn('encLightDescription',xml)


if __name__=='__main__': unittest.main()
