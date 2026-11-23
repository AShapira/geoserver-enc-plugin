#!/usr/bin/env python3
"""Compile the supported OpenCPN S-52 lookup subset into schema-aware GeoServer SLD.

GPL-2.0-or-later. This is a portrayal approximation, not an ECDIS renderer.
"""
import argparse
import copy
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET

SLD = 'http://www.opengis.net/sld'
OGC = 'http://www.opengis.net/ogc'
XLINK = 'http://www.w3.org/1999/xlink'
ET.register_namespace('', SLD)
ET.register_namespace('ogc', OGC)
ET.register_namespace('xlink', XLINK)
ROOT = Path(__file__).resolve().parents[1]
PRIORITIES = {'No data': 0, 'Group 1': 1, 'Area 1': 2, 'Area 2': 3,
              'Point Symbol': 4, 'Line Symbol': 5, 'Area Symbol': 6,
              'Routing': 7, 'Hazards': 8, 'Mariners': 9}
PORTRAYAL_FIELDS = {'_enc_line':'Geometry','_enc_line_normal':'Geometry','_enc_line_quality':'Geometry',
                    '_enc_lookup':'Integer','_enc_priority':'Integer','_enc_safety':'Integer','_enc_quapos':'Integer'}


def node(tag, text=None, *children, ns=SLD, **attrs):
    e = ET.Element(f'{{{ns}}}{tag}', attrs)
    if text is not None:
        e.text = str(text)
    e.extend(copy.deepcopy(list(children)))
    return e


def prop(name): return node('PropertyName', name, ns=OGC)
def lit(value): return node('Literal', value, ns=OGC)
def fun(name, *args): return node('Function', None, *args, ns=OGC, name=name)
def cmp(op, a, b): return node('PropertyIs' + op, None, a, b, ns=OGC)
def null(name): return node('PropertyIsNull', None, prop(name), ns=OGC)
def negate(x): return node('Not', None, x, ns=OGC)
def both(*args):
    a = [x for x in args if x is not None]
    return a[0] if len(a) == 1 else node('And', None, *a, ns=OGC)
def either(*args): return args[0] if len(args) == 1 else node('Or', None, *args, ns=OGC)
def css(name, value): return node('CssParameter', value, name=name)


def attribute_filter(code, fields):
    name, value = code[:6], code[6:]
    if name not in fields:
        return None if value == '?' else False
    if value == '?': return null(name)
    if not value or value == ' ': return negate(null(name))
    if fields[name] == 'String' and ',' not in value:
        comparison = cmp('EqualTo', fun('strMatches', prop(name), lit(r'(^|.*,)' + re.escape(value) + r'(,.*|$)')), lit(True))
    else:
        comparison = cmp('EqualTo', prop(name), lit(value))
    return both(negate(null(name)), comparison)


class Compiler:
    def __init__(self, upstream, out, palette='day', shallow=2, safety=5, deep=10, contour=None):
        if not 0 <= shallow <= safety <= deep:
            raise ValueError('Require 0 <= shallow <= safety <= deep')
        self.xml = ET.parse(upstream / 'chartsymbols.xml').getroot()
        self.out, self.palette = out, palette
        self.shallow, self.safety, self.deep = shallow, safety, deep
        self.contour = contour if contour is not None else safety
        table = {'day': 'DAY_BRIGHT', 'dusk': 'DUSK', 'night': 'NIGHT'}[palette]
        ct = next(c for c in self.xml.find('color-tables') if c.get('name') == table)
        self.colors = {c.get('name'): '#%02x%02x%02x' % tuple(int(c.get(k)) for k in ('r', 'g', 'b')) for c in ct.findall('color')}
        from PIL import Image
        self.atlas = Image.open(upstream / ct.find('graphics-file').get('name')).convert('RGBA')
        self.symbols = {s.findtext('name'): s for s in self.xml.find('symbols')}
        self.patterns = {s.findtext('name'): s for s in self.xml.find('patterns')}
        self.lines = {s.findtext('name'): s for s in self.xml.find('line-styles')}
        self.issues = set()
        self.assets = {}
        (out / 'symbols').mkdir(parents=True, exist_ok=True)

    def color(self, token):
        return self.colors.get(token, self.colors['CHMGD'])

    def fill(self, color):
        return node('PolygonSymbolizer', None, node('Fill', None, css('fill', self.color(color))))

    def line(self, color, width=1, dash='SOLD'):
        stroke = node('Stroke', None, css('stroke', self.color(color)), css('stroke-width', max(.6, float(width) * .6)))
        if dash != 'SOLD': stroke.append(css('stroke-dasharray', '6 4' if dash == 'DASH' else '1 3'))
        return node('LineSymbolizer', None, stroke)

    def vector_graphic(self, name, kind):
        from hpgl import render
        source = {'pattern': self.patterns, 'line': self.lines, 'symbol': self.symbols}[kind].get(name)
        if source is None:
            self.issues.add('Missing vector: ' + name)
            return None
        filename=f'{self.palette}_{kind}_{name}.png'
        try:
            raster=source.find('bitmap')
            if raster is not None and not (kind=='pattern' and source.findtext('definition')=='V'):
                location=raster.find('graphics-location')
                x,y=int(location.get('x')),int(location.get('y'))
                w,h=int(raster.get('width')),int(raster.get('height'))
                bitmap=self.atlas.crop((x,y,x+w,y+h))
            else:
                bitmap=render(source,self.colors,pattern=kind=='pattern',scale=1/28 if kind=='pattern' else .032)
            if kind=='pattern' and source.findtext('filltype')=='S':
                from PIL import Image
                tile=Image.new('RGBA',(bitmap.width,bitmap.height*2))
                tile.alpha_composite(bitmap,(0,0))
                tile.alpha_composite(bitmap,(bitmap.width//2,bitmap.height))
                tile.alpha_composite(bitmap,(bitmap.width//2-bitmap.width,bitmap.height))
                bitmap=tile
        except (ValueError,KeyError) as error:
            self.issues.add(f'Unsupported vector {name}: {error}')
            return None
        bitmap.save(self.out/'symbols'/filename)
        self.assets[filename]=list(bitmap.size)
        return node('Graphic',None,node('ExternalGraphic',None,
            node('OnlineResource',**{f'{{{XLINK}}}type':'simple',f'{{{XLINK}}}href':f'symbols/{filename}'}),
            node('Format','image/png')),node('Size',bitmap.height))

    def pattern(self,name):
        graphic=self.vector_graphic(name,'pattern')
        if graphic is None: return None
        self.issues.add('Pattern tiles: spacing and stagger supported; screen origin/clipping phase differs from OpenCPN')
        return node('PolygonSymbolizer',None,node('Fill',None,node('GraphicFill',None,graphic)))

    def complex_line(self,name):
        graphic=self.vector_graphic(name,'line')
        if graphic is None: return self.line('CHMGD',1,'DASH')
        self.issues.add('Complex lines: HPGL repeated stroke; corner joins and orientation differ from S-52')
        return node('LineSymbolizer',None,node('Stroke',None,node('GraphicStroke',None,graphic)))

    def symbol(self, name, rotation=None):
        s = self.symbols.get(name)
        bitmap = s.find('bitmap') if s is not None else None
        if bitmap is None:
            graphic=self.vector_graphic(name,'symbol')
            if graphic is not None: return node('PointSymbolizer',None,graphic)
            self.issues.add('Missing bitmap: ' + name)
            if name != 'QUESMRK1': return self.symbol('QUESMRK1')
            return None
        w, h = int(bitmap.get('width')), int(bitmap.get('height'))
        pos = bitmap.find('graphics-location')
        x, y = int(pos.get('x')), int(pos.get('y'))
        filename = f'{self.palette}_{name}.png'
        if filename not in self.assets:
            self.atlas.crop((x, y, x+w, y+h)).save(self.out / 'symbols' / filename)
            self.assets[filename] = [w, h]
        # SLD 1.0 has no Graphic AnchorPoint. Pad the bitmap so its S-52 pivot
        # is exactly at the image centre, preserving chart-object registration.
        pivot = bitmap.find('pivot')
        px, py = int(pivot.get('x')), int(pivot.get('y'))
        from PIL import Image
        if (px,py) == (-2147483648,-2147483648):
            self.issues.add('Unspecified bitmap pivot; centred symbol: '+name)
            px,py = w//2,h//2
        rw, rh = max(abs(px), abs(w-px)), max(abs(py), abs(h-py))
        canvas = Image.new('RGBA', (max(1, 2*rw), max(1, 2*rh)))
        canvas.alpha_composite(self.atlas.crop((x, y, x+w, y+h)), (rw-px, rh-py))
        canvas.save(self.out / 'symbols' / filename)
        self.assets[filename] = list(canvas.size)
        graphic = node('Graphic', None,
            node('ExternalGraphic', None, node('OnlineResource', **{f'{{{XLINK}}}type':'simple', f'{{{XLINK}}}href':f'symbols/{filename}'}), node('Format','image/png')),
            node('Size', canvas.height))
        if rotation is not None: graphic.append(node('Rotation', None, rotation))
        return node('PointSymbolizer', None, graphic)

    def native(self, kind, fields, **attributes):
        params={'palette':self.palette}
        for name,value in attributes.items():
            params[name]='${'+value+'}' if isinstance(value,str) and value in fields else str(value) if not isinstance(value,str) else ''
        url='file:/enc-s52/'+kind+'?'+'&'.join(f'{k}={v}' for k,v in params.items())
        return node('PointSymbolizer',None,node('Graphic',None,node('ExternalGraphic',None,
            node('OnlineResource',**{f'{{{XLINK}}}type':'simple',f'{{{XLINK}}}href':url}),
            node('Format','image/x-enc-s52')),node('Size',200 if kind=='light' else 64)))

    def text(self, label, color='CHBLK', size=16, placement=(0,0,1,-1), weight='normal'):
        sym = node('TextSymbolizer', None, node('Label', None, label),
                   node('Font', None, css('font-family','DejaVu Sans'), css('font-size',size),css('font-weight',weight)))
        ax,ay,dx,dy=placement
        point = node('PointPlacement', None, node('AnchorPoint', None, node('AnchorPointX',ax),node('AnchorPointY',ay)))
        point.append(node('Displacement', None, node('DisplacementX',dx*size*.6),node('DisplacementY',-dy*size)))
        sym.append(node('LabelPlacement',None,point))
        sym.append(node('Fill',None,css('fill',self.color(color))))
        sym.append(node('VendorOption','true',name='conflictResolution'))
        sym.append(node('VendorOption','2',name='spaceAround'))
        return sym

    def conditional(self, command, cls, geom, fields):
        """Return (additional filter, symbolizers) variants. Explicit approximations."""
        eq = lambda field, val: cmp('EqualTo', prop(field), lit(val))
        quality_field = '_enc_quapos' if '_enc_quapos' in fields else 'QUAPOS'
        def quality_lines(normal, low):
            if '_enc_line_quality' not in fields: return normal
            for symbol in normal: symbol.insert(0,node('Geometry',None,prop('_enc_line_normal')))
            low.insert(0,node('Geometry',None,prop('_enc_line_quality')))
            return normal+[low]
        if command == 'DEPARE01':
            if geom != 'Area': return [(None,[self.line('DEPCN')])]
            def threshold(name, default):
                return prop(name) if name in fields else lit(default)
            shallow = threshold('_enc_shallow_depth', self.shallow)
            safety = threshold('_enc_safety_depth', self.safety)
            deep = threshold('_enc_deep_depth', self.deep)
            bounds = [(lit(-1e9),lit(0),'DEPIT'),(lit(0),shallow,'DEPVS'),
                      (shallow,safety,'DEPMS'),(safety,deep,'DEPMD'),(deep,lit(1e9),'DEPDW')]
            result = [(null('DRVAL1'),[self.fill('DEPMD' if cls=='DRGARE' else 'NODTA')])]
            for low, high, color in bounds:
                result.append((both(cmp('GreaterThanOrEqualTo',prop('DRVAL1'),low),cmp('LessThan',prop('DRVAL1'),high)),[self.fill(color)]))
            # DEPARE01 corrects DRVAL2 <= DRVAL1 to DRVAL1 + .01; for valid depth
            # intervals these exclusive lower-bound bands give the same colour.
            if cls=='DRGARE':
                result=[(f,s+[self.pattern('DRGARE01'),self.line('CHGRF',1,'DASH')]) for f,s in result]
            return result
        if command == 'DEPCNT02':
            field = 'VALDCO' if 'VALDCO' in fields else 'DRVAL1'
            f = eq('_enc_safety',1) if '_enc_safety' in fields else cmp('EqualTo',prop(field),prop('_enc_safety_contour')) if '_enc_safety_contour' in fields else eq(field,self.contour)
            return [(f,quality_lines([self.line('DEPSC',2)],self.line('DEPSC',2,'DASH'))),
                    (either(null(field),negate(f)),quality_lines([self.line('DEPCN',1)],self.line('DEPCN',1,'DASH')))]
        if command == 'SOUNDG02':
            return [(None,[self.native('sounding',fields,depth='DEPTH',safety=('_enc_safety_depth' if '_enc_safety_depth' in fields else self.safety),
                tecsou='TECSOU',quasou='QUASOU',quapos=quality_field,status='STATUS')])]
        if command.startswith('LIGHTS'):
            graphic=self.native('light',fields,colour='COLOUR',catlit='CATLIT',sector1='SECTR1',sector2='SECTR2',
                range='VALNMR',orientation='ORIENT',visibility='LITVIS')
            label=fun('encLightDescription',*[prop(f) if f in fields else lit('') for f in
                ('LITCHR','SIGGRP','COLOUR','SIGPER','HEIGHT','VALNMR','SECTR1','CATLIT')])
            self.issues.add('Lights: co-located flare offsets and compound light groups remain approximate')
            return [(None,[graphic,self.text(label,placement=(0,1,2,-1))])]
        if command.startswith('WRECKS') and geom=='Point':
            graphic=self.native('wreck',fields,depth='VALSOU',safety=('_enc_safety_depth' if '_enc_safety_depth' in fields else self.safety),category='CATWRK',water='WATLEV',
                tecsou='TECSOU',quasou='QUASOU',quapos=quality_field,status='STATUS')
            self.issues.add('WRECKS02: attribute-based symbols/depth; surrounding-depth isolated-danger promotion incomplete')
            return [(negate(null('VALSOU')),[graphic,self.text(lit('Wk'),placement=(0,0,2,0))]),(null('VALSOU'),[graphic])]
        if command.startswith('WRECKS') or command.startswith('OBSTRN'):
            self.issues.add(command + ': conservative danger symbol; surrounding-depth and water-level procedures incomplete')
            return [(None,[self.symbol('DANGER01') if geom == 'Point' else self.line('CHBLK',2,'DOTT')])]
        if command.startswith(('QUAPOS','QUAPNT','QUALIN','SLCONS')):
            construction=command.startswith('SLCONS')
            if geom=='Point':
                if quality_field not in fields:return [(None,[])]
                low=both(cmp('GreaterThanOrEqualTo',prop(quality_field),lit(2)),cmp('LessThan',prop(quality_field),lit(10)))
                if construction:return [(low,[self.symbol('LOWACC01')]),(negate(low),[])]
                specials=[(eq(quality_field,4),'QUAPOS01'),(eq(quality_field,5),'QUAPOS02'),(either(eq(quality_field,7),eq(quality_field,8)),'QUAPOS03')]
                # LOWACC03 referenced by legacy OpenCPN code is absent from this
                # library; use its defined point low-accuracy symbol LOWACC01.
                return [(f,[self.symbol(name)]) for f,name in specials]+[(both(low,negate(either(*(f for f,_ in specials)))),[self.symbol('LOWACC01')]),(negate(low),[])]
            if construction:
                condition=lambda field,values: either(*(eq(field,v) for v in values)) if field in fields else cmp('EqualTo',lit(1),lit(0))
                choices=[(condition('CONDTN',[1,2]),1,'DASH'),(condition('CATSLC',[6,15,16]),4,'SOLD'),(condition('WATLEV',[3,4]),2,'DASH')]
                previous=[];result=[]
                for f,width,dash in choices+[(cmp('EqualTo',lit(1),lit(1)),2,'SOLD')]:
                    filt=both(f,negate(either(*previous)) if previous else None);previous.append(f)
                    symbols=quality_lines([self.line('CSTLN',width,dash)],self.complex_line('LOWACC21'))
                    if geom=='Area':symbols.insert(0,self.pattern('CROSSX01'))
                    result.append((filt,symbols))
                return result
            conspicuous=eq('CONRAD',1) if cls=='COALNE' and 'CONRAD' in fields else cmp('EqualTo',lit(1),lit(0))
            return [(conspicuous,quality_lines([self.line('CHMGF',3),self.line('CSTLN',1)],self.complex_line('LOWACC21'))),
                    (negate(conspicuous),quality_lines([self.line('CSTLN',1)],self.complex_line('LOWACC21')))]
        if command.startswith('RESARE') or command.startswith('RESTRN'):
            area=command.startswith('RESARE')
            symbols=[self.line('CHMGD',2,'DASH')] if area else []
            symbols.append(self.native('restriction',fields,restrn='RESTRN',catrea='CATREA',area=int(area)))
            return [(None,symbols)]
        if command.startswith('TOPMAR'):
            return [(None,[self.native('topmark',fields,shape='TOPSHP',floating='_enc_floating')])]
        self.issues.add('Unsupported conditional: ' + command)
        return [(None,[self.symbol('QUESMRK1')] if geom == 'Point' else [self.line('CHMGD',1,'DASH')])]

    def instructions(self, text, cls, geom, fields):
        # The pinned LNDARE point lookup has one missing CS closing parenthesis.
        # Repair that known record without modifying the licensed source asset.
        if cls=='LNDARE': text=text.replace('CS(QUAPOS01;','CS(QUAPOS01);')
        variants = [(None,[])]
        for op, raw in re.findall(r"([A-Z]{2})\(((?:'[^']*'|[^()])*)\)",text):
            args = next(csv.reader([raw],quotechar="'",skipinitialspace=True))
            symbols=[]
            if op=='AC': symbols=[self.fill(args[0])]
            elif op=='LS': symbols=[self.line(args[2],args[1],args[0])]
            elif op=='SY':
                rotation = None
                if len(args)>1:
                    rotation = prop(args[1]) if args[1] in fields else lit(float(args[1])) if re.fullmatch(r'-?[\d.]+',args[1]) else None
                symbols=[self.symbol(args[0],rotation)]
            elif op=='CS':
                extra=self.conditional(args[0],cls,geom,fields)
                variants=[(both(f,g) if f is not None or g is not None else None,s+[x for x in t if x is not None]) for f,s in variants for g,t in extra]
                continue
            elif op in ('TX','TE'):
                offset=1 if op=='TX' else 2
                if op=='TX':
                    if args[0] in fields: label=prop(args[0])
                    elif raw.startswith("'"): label=lit(args[0])
                    else: continue
                else:
                    names=args[1].split(',')
                    if any(f not in fields for f in names): continue
                    label=fun('encFormat',lit(args[0]),*[prop(f) for f in names])
                # Match the pinned OpenCPN reference's default 10 pt chart font
                # and its normalized S-52 body-size adjustment, at 96 dpi.
                hjust,vjust,_,chars,xoff,yoff,color=args[offset:offset+7]
                body=int(chars[3:]) if len(chars)>3 else 10
                size=round((10+int(min(body,20)/20*4))*96/72,2)
                if '=' in hjust or '=' in vjust:
                    self.issues.add('Attribute-driven label alignment uses lookup defaults')
                    hjust,vjust = hjust.split('=')[-1],vjust.split('=')[-1]
                placement=({1:.5,2:1,3:0}.get(int(hjust),0),{1:0,2:.5,3:1}.get(int(vjust),0),float(xoff),float(yoff))
                symbols=[self.text(label,color,size,placement,'bold' if len(chars)>1 and int(chars[1])>5 else 'normal')]
                self.issues.add('Text: native label collision/area placement differs from OpenCPN; font normalized at 96 dpi')
            elif op=='LC':
                symbols=[self.complex_line(args[0])]
            elif op=='AP': symbols=[self.pattern(args[0])]
            else: self.issues.add('Unsupported instruction: '+op)
            variants=[(f,s+[x for x in symbols if x is not None]) for f,s in variants]
        return variants

    def compile(self, cls, fields):
        groups=defaultdict(list)
        lookups=[l for l in self.xml.findall('lookups/lookup') if l.get('name')==cls and l.findtext('table-name') in ('Plain','Lines','Simplified')]
        for geom in ('Area','Line','Point'):
            candidates=[l for l in lookups if l.findtext('type')==geom]
            candidates.sort(key=lambda l:-len(l.findall('attrib-code')))
            previous=[]; seen=set()
            for l in candidates:
                codes=tuple(a.text for a in l.findall('attrib-code'))
                if codes in seen: continue
                seen.add(codes)
                conditions=[attribute_filter(c,fields) for c in codes]
                if any(c is False for c in conditions): continue
                conditions=[c for c in conditions if c is not None]
                condition=both(*conditions) if conditions else cmp('EqualTo',lit(1),lit(1))
                base=cmp('EqualTo',prop('_enc_lookup'),lit(l.get('RCID'))) if '_enc_lookup' in fields else both(
                    cmp('EqualTo',prop('PRIM'),lit({'Point':1,'Line':2,'Area':3}[geom])),condition,
                    negate(either(*previous)) if previous else None)
                previous.append(condition)
                if 'SCAMIN' in fields and l.findtext('display-cat')!='Displaybase':
                    visible=either(null('SCAMIN'),cmp('EqualTo',prop('SCAMIN'),lit(0)),cmp('LessThanOrEqualTo',fun('env',lit('enc_scale_denominator'),fun('env',lit('wms_scale_denominator'),lit(1))),prop('SCAMIN')))
                    if '_enc_safety' in fields:visible=either(cmp('EqualTo',prop('_enc_safety'),lit(1)),visible)
                    base=both(base,visible)
                prio=PRIORITIES.get(l.findtext('disp-prio'),5)
                priorities={prio}
                instruction=l.findtext('instruction') or ''
                if '_enc_priority' in fields:
                    if 'CS(RESARE02)' in instruction:priorities.add(6)
                    if 'CS(DEPCNT02)' in instruction:priorities.add(8)
                for extra,symbols in self.instructions(instruction,cls,geom,fields):
                    if not symbols: continue
                    if '_enc_line' in fields:
                        for symbol in symbols:
                            if symbol.tag==f'{{{SLD}}}LineSymbolizer' and symbol.find(f'{{{SLD}}}Geometry') is None: symbol.insert(0,node('Geometry',None,prop('_enc_line')))
                    for priority in sorted(priorities):
                        priority_filter=cmp('EqualTo',prop('_enc_priority'),lit(priority)) if '_enc_priority' in fields else None
                        rule=node('Rule',None,node('Name',f'{cls}-{l.get("RCID")}'),node('Filter',None,both(base,extra,priority_filter),ns=OGC),*symbols)
                        groups[priority].append(rule)
        if not groups and not cls.startswith('M_'):
            self.issues.add('No supported lookup for class: '+cls)
        return groups

    def write_style(self, name, rules):
        doc=node('StyledLayerDescriptor',None,node('NamedLayer',None,node('Name',name),
            node('UserStyle',None,node('Title',name),node('FeatureTypeStyle',None,*rules))),version='1.0.0')
        ET.indent(doc)
        ET.ElementTree(doc).write(self.out/f'{name}.sld',encoding='utf-8',xml_declaration=True)


def select_styles(library, palette, counts):
    entries = library['palettes'][palette]
    layers = {cls:{'style':name,'count':counts[cls]} for cls,name in entries['layers'].items() if counts.get(cls,0)>0}
    return {'layers':layers,'stack':[row for row in entries['stack'] if row['class'] in layers],
            'unportrayed_classes':{cls:n for cls,n in counts.items() if n and cls not in layers and not cls.startswith('M_')},
            'limitations':library['limitations'][palette],'library_revision':library['revision']}


def generate(gpkg, out, palette='day', shallow=2, safety=5, deep=10, library=None):
    from osgeo import ogr
    ogr.UseExceptions()
    dataset=ogr.Open(str(gpkg))
    if dataset is None: raise ValueError('Cannot open GeoPackage snapshot')
    dsid=dataset.GetLayerByName('DSID')
    if dsid is not None:
        metadata=dsid.GetNextFeature()
        if metadata is None or metadata.GetField('DSPM_DUNI') != 1:
            raise ValueError('Portrayal currently requires metre depth units (DSPM_DUNI=1)')
    if library is not None:
        coverage = dataset.GetLayerByName('M_COVR')
        if coverage is None or not coverage.GetFeatureCount():
            raise ValueError('ENC has no coverage geometry')
        x1,x2,y1,y2 = coverage.GetExtent()
        counts = {layer.GetName():layer.GetFeatureCount() for layer in dataset if layer.GetName()!='DSID'}
        return {**select_styles(library,palette,counts),'palette':palette,'bbox':[x1,y1,x2,y2],
                'shallow':shallow,'safety_depth':safety,'deep':deep}
    contours=[]
    layer=dataset.GetLayerByName('DEPCNT')
    if layer:
        contours=[f.GetField('VALDCO') for f in layer if f.GetField('VALDCO') is not None and f.GetField('VALDCO')>=safety]
    contour=min(contours) if contours else None
    compiler=Compiler(ROOT/'portrayal/upstream',out,palette,shallow,safety,deep,contour)
    layers={}; entries=[]
    for layer in dataset:
        cls=layer.GetName()
        if cls=='DSID' or cls.startswith('M_') or layer.GetFeatureCount()==0: continue
        schema=layer.GetLayerDefn()
        fields={schema.GetFieldDefn(i).GetName():schema.GetFieldDefn(i).GetTypeName() for i in range(schema.GetFieldCount())}
        if cls=='TOPMAR': fields['_enc_floating']='Integer'
        fields.update(PORTRAYAL_FIELDS)
        groups=compiler.compile(cls.removeprefix('i_'),fields)
        if not groups: continue
        merged=[]
        for priority,rules in sorted(groups.items()):
            name=f'enc_{palette}_{cls}_{priority}'
            compiler.write_style(name,rules); merged.extend(rules)
            entries.append({'class':cls,'style':name,'priority':priority})
        default=f'enc_{palette}_{cls}'
        compiler.write_style(default,merged)
        layers[cls]={'style':default,'count':layer.GetFeatureCount()}
    coverage=dataset.GetLayerByName('M_COVR')
    if coverage is None or coverage.GetFeatureCount()==0: raise ValueError('ENC has no coverage geometry')
    x1,x2,y1,y2=coverage.GetExtent()
    manifest={'palette':palette,'shallow':shallow,'safety_depth':safety,'deep':deep,'safety_contour':contour,
              'bbox':[x1,y1,x2,y2],'layers':layers,'stack':sorted(entries,key=lambda e:(e['priority'],e['class'])),
              'limitations':sorted(compiler.issues),'symbols':compiler.assets}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def generate_catalogue(index, out, palette='day', shallow=2, safety=5, deep=10, library=None):
    import sqlite3
    from osgeo import ogr
    with sqlite3.connect(index) as db:
        classes=dict(db.execute('SELECT class,SUM(features) FROM cell_classes GROUP BY class'))
        schemas={}
        for cls,name,kind in db.execute('SELECT class,name,type FROM fields ORDER BY class,ordinal'):
            schemas.setdefault(cls,{})[name]=kind
        active=db.execute('SELECT COUNT(*) FROM cells').fetchone()[0]
        bounds=[180.,90.,-180.,-90.]
        preview=None
        for (wkb,) in db.execute('SELECT coverage FROM cells ORDER BY name'):
            geom=ogr.CreateGeometryFromWkb(wkb)
            if geom.IsEmpty(): continue
            x1,x2,y1,y2=geom.GetEnvelope()
            bounds=[min(bounds[0],x1),min(bounds[1],y1),max(bounds[2],x2),max(bounds[3],y2)]
            if preview is None:
                point=geom.PointOnSurface()
                x,y=point.GetX(),point.GetY()
                preview=[x-.004,y-.003,x+.004,y+.003]
    if library is not None:
        return {**select_styles(library,palette,classes),'palette':palette,'active_cells':active,
                'shallow':shallow,'safety_depth':safety,'deep':deep,'bbox':bounds,'preview_bbox':preview}
    compiler=Compiler(ROOT/'portrayal/upstream',out,palette,shallow,safety,deep)
    layers={};entries=[]
    for cls,fields in sorted(schemas.items()):
        if cls.startswith('M_') or classes.get(cls,0)==0: continue
        fields={**fields,'_enc_cell':'String','_enc_cscl':'Integer','_enc_safety_contour':'Real'}
        if cls=='TOPMAR': fields['_enc_floating']='Integer'
        fields.update(PORTRAYAL_FIELDS)
        groups=compiler.compile(cls.removeprefix('i_'),fields)
        if not groups: continue
        merged=[]
        for priority,rules in sorted(groups.items()):
            name=f'enc_{palette}_{cls}_{priority}'
            compiler.write_style(name,rules);merged.extend(rules)
            entries.append({'class':cls,'style':name,'priority':priority})
        default=f'enc_{palette}_{cls}';compiler.write_style(default,merged)
        layers[cls]={'style':default,'count':classes[cls]}
    manifest={'palette':palette,'shallow':shallow,'safety_depth':safety,'deep':deep,
        'safety_contour':'per-cell first available at or deeper than safetyDepth','active_cells':active,
        'bbox':bounds,'preview_bbox':preview,
        'unportrayed_classes':{c:n for c,n in classes.items() if n and c not in layers and not c.startswith('M_')},
        'layers':layers,'stack':sorted(entries,key=lambda e:(e['priority'],e['class'])),
        'limitations':sorted(compiler.issues),'symbols':compiler.assets}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('gpkg',type=Path); p.add_argument('--out',type=Path,default=ROOT/'portrayal/generated')
    p.add_argument('--palette',choices=['day','dusk','night'],default='day')
    p.add_argument('--shallow',type=float,default=2); p.add_argument('--safety',type=float,default=5); p.add_argument('--deep',type=float,default=10)
    a=p.parse_args(); m=generate(a.gpkg,a.out,a.palette,a.shallow,a.safety,a.deep)
    print(f'Generated {len(m["stack"])} style passes, {len(m["symbols"])} symbols; limitations in {a.out}/manifest.json')
