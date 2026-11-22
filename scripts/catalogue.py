#!/usr/bin/env python3
"""Prepare a complete NOAA ENC catalogue for the S-57 GeoServer catalogue store.

All active cells are indexed, not a bounding-box subset. GDAL conversion to serving
GeoPackages is lazy in the Java plugin, so nationwide availability does not mean
opening thousands of native datasets during each map request.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import time
import xml.etree.ElementTree as ET
import zipfile

OPTIONS=['UPDATES=APPLY','SPLIT_MULTIPOINT=ON','ADD_SOUNDG_DEPTH=ON','LNAM_REFS=ON','LIST_AS_STRING=ON']


def clean_coverage(geometry, ogr):
    """Drop zero-area short rings that GEOS cannot ingest, retaining polygonal coverage."""
    if geometry.GetGeometryName()=='POLYGON':
        cleaned=ogr.Geometry(ogr.wkbPolygon)
        repairs=0
        for i in range(geometry.GetGeometryCount()):
            ring=geometry.GetGeometryRef(i)
            if ring.GetPointCount()<4:
                repairs+=1
                if i==0: break
            else:
                cleaned.AddGeometry(ring)
        return cleaned,repairs
    if geometry.GetGeometryName() in ('MULTIPOLYGON','GEOMETRYCOLLECTION'):
        result=ogr.Geometry(ogr.wkbMultiPolygon)
        repairs=0
        for i in range(geometry.GetGeometryCount()):
            polygon,count=clean_coverage(geometry.GetGeometryRef(i),ogr)
            repairs+=count
            if not polygon.IsEmpty():
                if polygon.GetGeometryName()=='POLYGON':result.AddGeometry(polygon)
                else:
                    for j in range(polygon.GetGeometryCount()):result.AddGeometry(polygon.GetGeometryRef(j))
        return result,repairs
    return ogr.Geometry(ogr.wkbPolygon),1


def inspect_cell(task):
    from osgeo import gdal,ogr
    gdal.UseExceptions();ogr.UseExceptions()
    name,filename,relative,title,expected_edition,expected_update=task
    ds=gdal.OpenEx(filename,gdal.OF_VECTOR,allowed_drivers=['S57'],open_options=OPTIONS)
    metadata=ds.GetLayerByName('DSID').GetNextFeature()
    edition=int(metadata.GetField('DSID_EDTN'));update=int(metadata.GetField('DSID_UPDN'))
    if expected_edition is not None and (edition!=expected_edition or update!=expected_update):
        raise ValueError(f'{name}: catalogue requires {expected_edition}/{expected_update}, GDAL read {edition}/{update}')
    declared=Path(metadata.GetField('DSID_DSNM')).stem
    if expected_edition is not None and declared.casefold()!=name.casefold():
        raise ValueError(f'{name}: mismatched DSID cell name {declared}')
    if edition==0:
        return {'cancelled':name}
    sidecars=sorted(int(p.suffix[1:]) for p in Path(filename).parent.glob(name+'.[0-9][0-9][0-9]') if p.suffix!='.000')
    if sidecars:
        base=gdal.OpenEx(filename,gdal.OF_VECTOR,allowed_drivers=['S57'],open_options=['UPDATES=IGNORE'])
        initial=int(base.GetLayerByName('DSID').GetNextFeature().GetField('DSID_UPDN'))
        if [u for u in sidecars if u>initial]!=list(range(initial+1,update+1)) or sidecars[-1]!=update:
            raise ValueError(f'{name}: incomplete update chain after {initial}, found {sidecars}, applied {update}')
    if metadata.GetField('DSPM_DUNI')!=1: raise ValueError(f'{name}: unsupported depth units')
    scale=int(metadata.GetField('DSPM_CSCL'));coverage=None;exclusions=None
    layer=ds.GetLayerByName('M_COVR')
    if layer is None: raise ValueError(f'{name}: no M_COVR')
    repairs=0
    unclassified=False
    for f in layer:
        geometry=f.GetGeometryRef()
        if geometry is None: continue
        g=geometry.Clone();g.FlattenTo2D()
        g,removed=clean_coverage(g,ogr)
        repairs+=removed
        if g.IsEmpty(): continue
        if not g.IsValid(): g=g.MakeValid();repairs+=1
        if f.GetField('CATCOV')==1: coverage=g if coverage is None else coverage.Union(g)
        elif f.GetField('CATCOV')==2: exclusions=g if exclusions is None else exclusions.Union(g)
        else: unclassified=True
    if coverage is None:
        if not unclassified or exclusions is not None:
            raise ValueError(f'{name}: no positive coverage')
        coverage=ogr.Geometry(ogr.wkbMultiPolygon)
    if exclusions is not None: coverage=coverage.Difference(exclusions)
    if coverage.IsEmpty() and not unclassified: raise ValueError(f'{name}: empty coverage')
    # Break multipolygon coverage into individual envelopes in the Java STRtree;
    # cells straddling 180 degrees must not force an all-world spatial candidate.
    classes={};schemas={};contours=[]
    for i in range(ds.GetLayerCount()):
        layer=ds.GetLayerByIndex(i)
        cls=layer.GetName()
        if cls=='DSID': continue
        definition=layer.GetLayerDefn()
        classes[cls]=layer.GetFeatureCount()
        schemas[cls]=[(definition.GetFieldDefn(i).GetName(),definition.GetFieldDefn(i).GetTypeName()) for i in range(definition.GetFieldCount())]
        if cls=='DEPCNT':
            contours=sorted({float(f.GetField('VALDCO')) for f in layer if f.GetField('VALDCO') is not None})
    return {'name':declared,'filename_cell':name,'path':relative,'title':title,'scale':scale,'band':(99 if name[2:3].upper()=='B' or metadata.GetField('DSID_INTU')==10 else int(metadata.GetField('DSID_INTU'))),'agency':metadata.GetField('DSID_AGEN'),'edition':edition,'update':update,
            'coverage':bytes(coverage.ExportToWkb()),'classes':classes,'schemas':schemas,'contours':contours,'coverage_repairs':repairs,'unclassified_coverage':coverage.IsEmpty()}


def prepare(catalogue,archive,out,workers=4):
    out.mkdir(parents=True,exist_ok=True)
    digest=hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()
    revision=out/'exchanges'/digest[:20]
    complete=revision/'.extracted'
    if not complete.exists():
        revision.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                p=PurePosixPath(info.filename)
                if p.is_absolute() or '..' in p.parts or '\\' in info.filename: raise ValueError('Unsafe exchange-set ZIP path')
            print(f'Extracting {len(z.infolist())} entries, {sum(i.file_size for i in z.infolist())/1e9:.2f} GB',flush=True)
            z.extractall(revision)
        complete.write_text(digest+'\n')
    root=ET.parse(catalogue).getroot()
    active=[c for c in root.findall('cell') if c.findtext('status')=='Active']
    files={p.stem:p for p in revision.rglob('*.000') if p.stem.startswith('US')}
    missing=sorted(c.findtext('name') for c in active if c.findtext('name') not in files)
    if missing: raise ValueError(f'{len(missing)} active cells missing from exchange set: {missing[:20]}')
    tasks=[(c.findtext('name'),str(files[c.findtext('name')]),str(files[c.findtext('name')].relative_to(out)),
            c.findtext('lname'),int(c.findtext('edtn')),int(c.findtext('updn'))) for c in active]
    return write_index(tasks,out,workers,{'catalogue_valid':root.findtext('Header/dt_valid'),
        'catalogue_sha256':hashlib.file_digest(catalogue.open('rb'),'sha256').hexdigest(),
        'archive_sha256':digest,'cancelled_cells':len(root.findall('cell'))-len(active)})


def write_index(tasks,out,workers,source):
    started=time.monotonic()
    partial=out/'catalogue.sqlite.partial'
    if partial.exists(): partial.unlink()
    db=sqlite3.connect(partial)
    db.executescript('''
      CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
      CREATE TABLE cells(name TEXT PRIMARY KEY,path TEXT,title TEXT,cscale INTEGER,band INTEGER,edition INTEGER,updn INTEGER,coverage BLOB,contours TEXT);
      CREATE TABLE producers(cell TEXT PRIMARY KEY, agency INTEGER);
      CREATE TABLE cell_classes(cell TEXT,class TEXT,features INTEGER,PRIMARY KEY(cell,class));
      CREATE TABLE fields(class TEXT,name TEXT,type TEXT,ordinal INTEGER,PRIMARY KEY(class,name));
    ''')
    schemas={};failures=[];repairs=0;features=0;class_counts={}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pending={pool.submit(inspect_cell,t):t[0] for t in tasks}
        for i,future in enumerate(as_completed(pending),1):
            try:
                c=future.result()
                if 'cancelled' in c:
                    source['cancelled_cells']+=1
                    continue
                if c['unclassified_coverage']:
                    source.setdefault('unclassified_coverage',[]).append(c['name'])
                if c['name']!=c['filename_cell']:
                    source.setdefault('filename_aliases',{})[c['filename_cell']]=c['name']
                db.execute('INSERT INTO producers VALUES (?,?)',(c['name'],c['agency']))
                db.execute('INSERT INTO cells VALUES (?,?,?,?,?,?,?,?,?)',(c['name'],c['path'],c['title'],c['scale'],c['band'],c['edition'],c['update'],c['coverage'],','.join(map(str,c['contours']))))
                for cls,count in c['classes'].items():
                    db.execute('INSERT INTO cell_classes VALUES (?,?,?)',(c['name'],cls,count));features+=count
                    class_counts[cls]=class_counts.get(cls,0)+count
                for cls,fields in c['schemas'].items():
                    destination=schemas.setdefault(cls,{})
                    for name,kind in fields:
                        if name in destination and destination[name]!=kind: raise ValueError(f'Conflicting schema for {cls}.{name}')
                        destination[name]=kind
                repairs+=c['coverage_repairs']
            except Exception as error:
                failures.append({'cell':pending[future],'error':str(error)})
                print('FAILED',pending[future],str(error),flush=True)
            if i%100==0 or i==len(tasks):
                db.commit();print(f'Indexed {i}/{len(tasks)}, {len(failures)} failures, {features:,} features, {time.monotonic()-started:.1f}s',flush=True)
    indexed=db.execute('SELECT count(*) FROM cells').fetchone()[0]
    if indexed and len(source.get('unclassified_coverage',[])) == indexed:
        failures.append({'error':'No cells declare positive coverage'})
    if not indexed and not failures:
        failures.append({'error':'No active chart cells'})
    report={**source,'prepared_utc':datetime.now(timezone.utc).isoformat(),
            'active_cells':indexed+len(failures),'indexed_cells':indexed,
            'features':features,'classes':class_counts,'coverage_repairs':repairs,'failures':failures,'seconds':round(time.monotonic()-started,1)}
    (out/'catalogue-report.json').write_text(json.dumps(report,indent=2)+'\n')
    if failures:
        db.close();raise RuntimeError(f'Catalogue not published: {len(failures)} cells failed; see catalogue-report.json')
    for cls,fields in sorted(schemas.items()):
        for i,(name,kind) in enumerate(fields.items()): db.execute('INSERT INTO fields VALUES (?,?,?,?)',(cls,name,kind,i))
    for key,value in {'format':'enc-catalogue-1','active_cells':str(indexed),'archive_sha256':source['archive_sha256'],'created':report['prepared_utc']}.items():
        db.execute('INSERT INTO metadata VALUES (?,?)',(key,value))
    db.execute('CREATE INDEX class_cells ON cell_classes(class)');db.commit();db.close()
    partial.replace(out/'catalogue.sqlite')
    print('Catalogue ready:',out/'catalogue.sqlite',flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--catalogue',type=Path,required=True);p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--workers',type=int,default=4)
    a=p.parse_args();prepare(a.catalogue,a.archive,a.out,a.workers)
