#!/usr/bin/env python3
"""Publish chart layers and a WMTS chart group using the installed ENC style library."""
import argparse
import base64
import json
import math
import time
from types import SimpleNamespace
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from portrayal import generate, generate_catalogue
from cache_key import snapshot_path


class Server:
    def __init__(self,url,user,password):
        self.url=url.rstrip('/')
        self.auth='Basic '+base64.b64encode(f'{user}:{password}'.encode()).decode()
    def request(self,method,path,data=None,content_type='application/json'):
        if isinstance(data,(dict,list)): data=json.dumps(data).encode()
        r=urllib.request.Request(self.url+path,data=data,method=method,
            headers={'Authorization':self.auth,'Content-Type':content_type,'Accept':'application/json'})
        try:
            with urllib.request.urlopen(r,timeout=360) as response: return response.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f'{method} {path}: {e.code}: {e.read().decode()[:2500]}') from e
    def exists(self,path):
        try: self.request('GET',path+('&' if '?' in path else '?')+'quietOnNotFound=true'); return True
        except RuntimeError as e:
            if ': 404:' in str(e): return False
            raise


def installed_library(server):
    library = json.loads(server.request('GET','/rest/resource/styles/enc-library-v1/manifest.json'))
    if library.get('schema_version') != 1:
        raise ValueError('Install the compatible ENC style library before publishing')
    catalog = json.loads(server.request('GET','/rest/styles.json')).get('styles') or {}
    names = {entry['name'] for entry in catalog.get('style',[])}
    missing = {path[:-4] for path in library['checksums'] if path.endswith('.sld')} - names
    if missing:
        raise ValueError('Incomplete ENC style installation: '+', '.join(sorted(missing)[:5]))
    return library


def truncate_tiles(server, group):
    path = '/gwc/rest/seed/'+group+'.json'
    for grid in (900913,4326):
        server.request('POST',path,{'seedRequest':{'name':group,'srs':{'number':grid},
            'zoomStart':0,'zoomStop':22,'format':'image/png','type':'truncate','threadCount':1}})
    deadline = time.monotonic()+600
    while True:
        tasks = json.loads(server.request('GET',path)).get('long-array-array',[])
        if not tasks:
            return
        if any(len(t)>4 and t[4] in (-1,3) for t in tasks) or time.monotonic()>deadline:
            raise RuntimeError('Cache truncation failed or timed out for '+group)
        time.sleep(0.5)


def store_depths(params):
    safety = float(params.get('safetyDepth',5))
    return (float(params.get('shallowDepth',min(2,safety))),safety,
            float(params.get('deepDepth',max(10,safety))))


def publish_catalogue(directory, workspace, title, profile, index=None, cache=None, ogr=None):
    index = index or directory/'catalogue.sqlite'
    cache = cache or directory/'cache'
    cache.mkdir(parents=True,exist_ok=True)
    title = title or profile.get('title') or workspace
    data_dir = Path(os.environ.get('GEOSERVER_DATA_DIR','/opt/geoserver_data'))
    registry = data_dir/'www'/'enc-sources.json'
    registry.parent.mkdir(exist_ok=True)
    records = json.loads(registry.read_text()) if registry.exists() else {}
    args=SimpleNamespace(cell=None,catalogue=index,workspace=workspace,title=title,cache=cache,
        ogr2ogr=ogr or Path('/opt/enc/scripts/ogr_inland.py'),data_dir=data_dir,
        url=os.environ.get('GEOSERVER_URL', 'http://127.0.0.1:8080/geoserver'),user=os.environ.get('GEOSERVER_USER') or 'admin',
        password=os.environ.get('GEOSERVER_PASSWORD') or 'geoserver',shallow=2,safety=5,deep=10,update=True,all_palettes=True)
    server=Server(args.url,args.user,args.password)
    args.attribution = profile.get('attribution', '')
    args.library = installed_library(server)
    store='/rest/workspaces/'+workspace+'/datastores/chart.json'
    current_index = None
    if server.exists('/rest/workspaces/'+workspace+'.json'):
        if server.exists(store):
            settings=json.loads(server.request('GET',store))['dataStore']['connectionParameters']['entry']
            parameters = {entry.get('@key'):entry.get('$') for entry in settings}
            args.shallow,args.safety,args.deep = store_depths(parameters)
            current_index = parameters.get('catalogue')
            if parameters.get('dbtype') != 's57' or not current_index:
                raise ValueError('Existing chart store is not an S-57 catalogue: '+workspace)
        elif not (directory/'.publishing').exists():
            raise ValueError('Existing workspace is not an ENC catalogue: '+workspace)
    previous = records.get(workspace,{})
    generation = index.parent.name
    if not re.fullmatch('[0-9a-f]{64}',generation):
        import sqlite3
        with sqlite3.connect(index) as db:
            generation = db.execute("SELECT value FROM metadata WHERE key='archive_sha256'").fetchone()[0]
    if (previous.get('generation') == generation and previous.get('title') == title
            and current_index == str(index) and previous.get('view') == profile.get('view',previous.get('view'))
            and previous.get('wms_attribution') == args.attribution
            and previous.get('depths') == [args.shallow,args.safety,args.deep]
            and previous.get('library_revision') == args.library['revision'] and not (directory/'.publishing').exists()
            and all(server.exists('/rest/workspaces/'+workspace+'/layergroups/chart_'+p+'.json')
                    for p in ('day','dusk','night'))):
        print(f'{workspace} already serves generation {generation}')
        return
    # REST changes several resources. A retry must replay every palette if a
    # previous attempt was interrupted, even if it targeted the same store.
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'.publishing').touch()
    for palette in ('day','dusk','night'):
        args.palette=palette
        args.styles=directory/('portrayal-'+palette)
        result=publish(args)
    bbox=result['preview_bbox']
    view=profile.get('view') or [(bbox[0]+bbox[2])/2,(bbox[1]+bbox[3])/2,16]
    records[workspace]={'title':title,'product':profile.get('product','S-57 ENC'),
        'attribution':args.attribution,'wms_attribution':args.attribution,'source':profile.get('source',''),
        'view':view,'bbox':result['bbox'],'cells':result['active_cells'],'depths':[args.shallow,args.safety,args.deep],'generation':generation,'library_revision':args.library['revision']}
    temp=registry.with_suffix('.tmp')
    temp.write_text(json.dumps(records,indent=2,ensure_ascii=False)+'\n')
    os.replace(temp,registry)
    (directory/'.publishing').unlink()


def publish(a):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',a.workspace): raise ValueError('Use a simple workspace identifier')
    if not a.password: raise ValueError('Set GEOSERVER_PASSWORD')
    server=Server(a.url,a.user,a.password)
    library = getattr(a,'library',None) or installed_library(server)
    if bool(a.cell) == bool(a.catalogue): raise ValueError('Specify exactly one cell or --catalogue')
    ws=f'/rest/workspaces/{a.workspace}'
    store=ws+'/datastores/chart'
    exists = server.exists(ws+'.json')
    if exists and not a.update:
        raise ValueError('Workspace exists; use a new workspace or --update for this plugin-owned workspace')
    previous = {}
    store_exists = exists and server.exists(store+'.json')
    if store_exists:
        settings = json.loads(server.request('GET',store+'.json'))['dataStore']['connectionParameters']['entry']
        previous = {e['@key']:e.get('$') for e in settings}
    prior = store_depths(previous)
    for field,default in zip(('shallow','safety','deep'),prior):
        if getattr(a,field) is None:
            setattr(a,field,default)
    if not 0 <= a.shallow <= a.safety <= a.deep or not math.isfinite(a.deep):
        raise ValueError('Require finite depths with 0 <= shallow <= safety <= deep')
    if not exists:
        server.request('POST','/rest/workspaces',{'workspace':{'name':a.workspace}})
    title=getattr(a,'title',None) or (a.cell.stem if a.cell else ('Full NOAA catalogue' if a.workspace=='noaa' else a.workspace))
    params={'dbtype':'s57','cache':str(a.cache.resolve()),'safetyDepth':str(a.safety),'shallowDepth':str(a.shallow),'deepDepth':str(a.deep),'cellPoolSize':'32',
            'ogr2ogr':str(a.ogr2ogr.resolve()),'namespace':f'https://example.org/enc/{a.workspace}','timeout':'300'}
    params['catalogue' if a.catalogue else 'file']=str((a.catalogue or a.cell).resolve())
    body={'dataStore':{'name':'chart','enabled':True,'connectionParameters':{'entry':[{'@key':k,'$':v} for k,v in params.items()]}}}
    server.request('PUT' if store_exists else 'POST',store if store_exists else ws+'/datastores',body)
    # Force opening the GDAL-backed store before reading the newly generated cache.
    server.request('GET',store+'/featuretypes.json?list=available')
    gpkg=None
    if a.catalogue:
        manifest=generate_catalogue(a.catalogue,a.styles,a.palette,a.shallow,a.safety,a.deep,library=library)
    else:
        gpkg=snapshot_path(a.cell,a.cache,a.ogr2ogr)
        if not gpkg.is_file(): raise RuntimeError('Plugin did not create the expected snapshot: '+str(gpkg))
        manifest=generate(gpkg,a.styles,a.palette,a.shallow,a.safety,a.deep,library=library)
    attribution = {'attribution': {'title': a.attribution}} if getattr(a, 'attribution', '') else {}
    for cls,info in manifest['layers'].items():
        ft=store+'/featuretypes/'+cls
        exists=server.exists(ft+'.json')
        server.request('PUT' if exists else 'POST',ft if exists else store+'/featuretypes',{'featureType':{'name':cls,'nativeName':cls,'title':f'{title} — {cls}',
                'srs':'EPSG:4326','projectionPolicy':'FORCE_DECLARED','enabled':True,
                'nativeBoundingBox':{'minx':manifest['bbox'][0],'miny':manifest['bbox'][1],'maxx':manifest['bbox'][2],'maxy':manifest['bbox'][3],'crs':'EPSG:4326'},
                'latLonBoundingBox':{'minx':manifest['bbox'][0],'miny':manifest['bbox'][1],'maxx':manifest['bbox'][2],'maxy':manifest['bbox'][3],'crs':'EPSG:4326'}}})
        server.request('PUT',f'/rest/layers/{a.workspace}:{cls}',{'layer':{'defaultStyle':{'name':info["style"]},'enabled':True, **attribution}})
    name='chart_'+a.palette
    stack=manifest['stack']; x1,y1,x2,y2=manifest['bbox']
    group={'layerGroup':{'name':name,'mode':'SINGLE',**attribution,'title':f'{title} ENC ({a.palette})',
        'abstractTxt':'GDAL S-57 with S-52-derived portrayal. Experimental; see portrayal limitations.',
        'publishables':{'published':[{'@type':'layer','name':f'{a.workspace}:{e["class"]}'} for e in stack]},
        'styles':{'style':[{'name':e["style"]} for e in stack]},
        'bounds':{'minx':x1,'miny':y1,'maxx':x2,'maxy':y2,'crs':'EPSG:4326'}}}
    path=ws+'/layergroups/'+name
    server.request('PUT' if server.exists(path+'.json') else 'POST',path if server.exists(path+'.json') else ws+'/layergroups',group)
    # Enforce buffered metatiling; use fixed portrayal presets as separate cache keys.
    gwc=f'/gwc/rest/layers/{a.workspace}:{name}.xml'
    config=ET.fromstring(server.request('GET',gwc))
    config.find('gutter').text='64'
    meta=config.find('metaWidthHeight')
    for value in meta: value.text='4'
    server.request('PUT',gwc,ET.tostring(config),'application/xml')
    if a.update:
        groups = [name] if getattr(a,'all_palettes',False) else [
            'chart_'+p for p in ('day','dusk','night')
            if p == a.palette or server.exists(ws+'/layergroups/chart_'+p+'.json')]
        for group_name in groups:
            truncate_tiles(server,a.workspace+':'+group_name)
    params={'service':'WMS','version':'1.1.1','request':'GetMap','layers':f'{a.workspace}:{name}','styles':'','srs':'EPSG:4326',
        'bbox':','.join(map(str,manifest.get('preview_bbox',manifest['bbox']))),'width':1000,'height':1000,'format':'image/png'}
    manifest['wms_url']=server.url+'/wms?'+urllib.parse.urlencode(params)
    manifest['wmts_url']=server.url+'/gwc/service/wmts?SERVICE=WMTS&REQUEST=GetCapabilities'
    manifest['workspace']=a.workspace; manifest['group']=name; manifest['cache']=str(gpkg)
    a.styles.mkdir(parents=True,exist_ok=True)
    (a.styles/'publication.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(manifest['wms_url']); print(manifest['wmts_url'],flush=True)
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('cell',type=Path,nargs='?'); p.add_argument('--catalogue',type=Path); p.add_argument('--url',default='http://127.0.0.1:18080/geoserver')
    p.add_argument('--user',default=os.environ.get('GEOSERVER_USER','admin'))
    p.add_argument('--password',default=os.environ.get('GEOSERVER_PASSWORD'))
    p.add_argument('--workspace',default='noaa'); p.add_argument('--data-dir',type=Path,help='Accepted for compatibility; symbols are bundled with the plugin')
    p.add_argument('--cache',required=True,type=Path); p.add_argument('--ogr2ogr',required=True,type=Path)
    p.add_argument('--styles',type=Path,default=Path('portrayal/generated'))
    p.add_argument('--palette',choices=['day','dusk','night'],default='day'); p.add_argument('--update',action='store_true')
    p.add_argument('--shallow',type=float); p.add_argument('--safety',type=float); p.add_argument('--deep',type=float)
    publish(p.parse_args())
