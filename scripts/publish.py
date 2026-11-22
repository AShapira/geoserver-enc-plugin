#!/usr/bin/env python3
"""Publish a cell through the S-57 plugin, compile SLDs, and create a WMTS chart group.
Requires local access to the server data directory for symbol assets.
"""
import argparse
import base64
import json
import hashlib
import tempfile
import time
from types import SimpleNamespace
import os
from pathlib import Path
import re
import shutil
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


def shared_styles(server, data_dir, directory, manifest):
    """Install immutable global styles. Relative graphics resolve from global styles/."""
    symbols = data_dir / 'styles' / 'enc-symbols'
    symbols.mkdir(parents=True,exist_ok=True)
    assets = {}
    for png in (directory/'symbols').glob('*.png'):
        data = png.read_bytes()
        filename = hashlib.sha256(data).hexdigest() + '.png'
        if not (symbols/filename).exists():
            with tempfile.NamedTemporaryFile(dir=symbols,delete=False) as tmp:
                tmp.write(data)
                os.fchmod(tmp.fileno(),0o644)
            os.replace(tmp.name,symbols/filename)
        assets['symbols/'+png.name] = 'enc-symbols/'+filename
    catalog = json.loads(server.request('GET','/rest/styles.json')).get('styles') or {}
    existing = {entry['name'] for entry in catalog.get('style',[])}
    mapped = {}
    for info in [*manifest['layers'].values(),*manifest['stack']]:
        name = info['style']
        if name not in mapped:
            doc = ET.parse(directory/(name+'.sld'))
            for resource in doc.iter('{http://www.opengis.net/sld}OnlineResource'):
                key = '{http://www.w3.org/1999/xlink}href'
                href = resource.get(key,'')
                if href.startswith('symbols/'):
                    resource.set(key,assets[href])
            data = ET.tostring(doc.getroot(),encoding='utf-8',xml_declaration=True)
            key = name + '_' + hashlib.sha256(data).hexdigest()[:20]
            if key not in existing:
                server.request('POST','/rest/styles?name='+key,data,'application/vnd.ogc.sld+xml')
                existing.add(key)
            mapped[name] = key
        info['style'] = mapped[name]


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
        ogr2ogr=ogr or Path('/opt/enc/scripts/ogr_inland.py'),data_dir=data_dir,shared=True,
        url='http://127.0.0.1:8080/geoserver',user=os.environ.get('GEOSERVER_USER') or 'admin',
        password=os.environ.get('GEOSERVER_PASSWORD') or 'geoserver',shallow=2,safety=5,deep=10,update=True)
    server=Server(args.url,args.user,args.password)
    store='/rest/workspaces/'+workspace+'/datastores/chart.json'
    current_index = None
    if server.exists('/rest/workspaces/'+workspace+'.json'):
        if server.exists(store):
            settings=json.loads(server.request('GET',store))['dataStore']['connectionParameters']['entry']
            parameters = {entry.get('@key'):entry.get('$') for entry in settings}
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
            and previous.get('portrayal_version') == 2 and not (directory/'.publishing').exists()
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
        'attribution':profile.get('attribution',''),'source':profile.get('source',''),
        'view':view,'bbox':result['bbox'],'cells':result['active_cells'],'generation':generation,'portrayal_version':2}
    temp=registry.with_suffix('.tmp')
    temp.write_text(json.dumps(records,indent=2,ensure_ascii=False)+'\n')
    os.replace(temp,registry)
    (directory/'.publishing').unlink()


def publish(a):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',a.workspace): raise ValueError('Use a simple workspace identifier')
    if not a.password: raise ValueError('Set GEOSERVER_PASSWORD')
    server=Server(a.url,a.user,a.password)
    ws=f'/rest/workspaces/{a.workspace}'
    if server.exists(ws+'.json'):
        if not a.update: raise ValueError('Workspace exists; use a new workspace or --update for this plugin-owned workspace')
    else: server.request('POST','/rest/workspaces',{'workspace':{'name':a.workspace}})
    store=ws+'/datastores/chart'
    if bool(a.cell) == bool(a.catalogue): raise ValueError('Specify exactly one cell or --catalogue')
    title=getattr(a,'title',None) or (a.cell.stem if a.cell else ('Full NOAA catalogue' if a.workspace=='noaa' else a.workspace))
    params={'dbtype':'s57','cache':str(a.cache.resolve()),'safetyDepth':str(a.safety),'cellPoolSize':'32',
            'ogr2ogr':str(a.ogr2ogr.resolve()),'namespace':f'https://example.org/enc/{a.workspace}','timeout':'300'}
    params['catalogue' if a.catalogue else 'file']=str((a.catalogue or a.cell).resolve())
    body={'dataStore':{'name':'chart','enabled':True,'connectionParameters':{'entry':[{'@key':k,'$':v} for k,v in params.items()]}}}
    server.request('PUT' if server.exists(store+'.json') else 'POST',store if server.exists(store+'.json') else ws+'/datastores',body)
    # Force opening the GDAL-backed store before reading the newly generated cache.
    available=json.loads(server.request('GET',store+'/featuretypes.json?list=available'))
    gpkg=None
    if a.catalogue:
        manifest=generate_catalogue(a.catalogue,a.styles,a.palette,a.shallow,a.safety,a.deep)
    else:
        gpkg=snapshot_path(a.cell,a.cache,a.ogr2ogr)
        if not gpkg.is_file(): raise RuntimeError('Plugin did not create the expected snapshot: '+str(gpkg))
        manifest=generate(gpkg,a.styles,a.palette,a.shallow,a.safety,a.deep)
    shared=getattr(a,'shared',False)
    if shared:
        shared_styles(server,a.data_dir,a.styles,manifest)
    else:
        target=a.data_dir/'workspaces'/a.workspace/'styles'/'symbols'
        target.mkdir(parents=True,exist_ok=True)
        for asset in (a.styles/'symbols').glob('*.png'): shutil.copy2(asset,target/asset.name)
        styles={v['style'] for v in manifest['layers'].values()}|{v['style'] for v in manifest['stack']}
        for name in sorted(styles):
            path=ws+'/styles/'+name
            data=(a.styles/f'{name}.sld').read_bytes()
            if server.exists(path+'.json'): server.request('PUT',path,data,'application/vnd.ogc.sld+xml')
            else: server.request('POST',ws+'/styles?name='+name,data,'application/vnd.ogc.sld+xml')
    prefix='' if shared else a.workspace+':'
    for cls,info in manifest['layers'].items():
        ft=store+'/featuretypes/'+cls
        exists=server.exists(ft+'.json')
        if not exists or shared:
            server.request('PUT' if exists else 'POST',ft if exists else store+'/featuretypes',{'featureType':{'name':cls,'nativeName':cls,'title':f'{title} — {cls}',
                'srs':'EPSG:4326','projectionPolicy':'FORCE_DECLARED','enabled':True,
                'nativeBoundingBox':{'minx':manifest['bbox'][0],'miny':manifest['bbox'][1],'maxx':manifest['bbox'][2],'maxy':manifest['bbox'][3],'crs':'EPSG:4326'},
                'latLonBoundingBox':{'minx':manifest['bbox'][0],'miny':manifest['bbox'][1],'maxx':manifest['bbox'][2],'maxy':manifest['bbox'][3],'crs':'EPSG:4326'}}})
        server.request('PUT',f'/rest/layers/{a.workspace}:{cls}',{'layer':{'defaultStyle':{'name':prefix+info["style"]},'enabled':True}})
    name='chart_'+a.palette
    stack=manifest['stack']; x1,y1,x2,y2=manifest['bbox']
    group={'layerGroup':{'name':name,'mode':'SINGLE','title':f'{title} ENC ({a.palette})',
        'abstractTxt':'GDAL S-57 with S-52-derived portrayal. Experimental; see portrayal limitations.',
        'publishables':{'published':[{'@type':'layer','name':f'{a.workspace}:{e["class"]}'} for e in stack]},
        'styles':{'style':[{'name':prefix+e["style"]} for e in stack]},
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
        server.request('POST',f'/gwc/rest/seed/{a.workspace}:{name}.json',{'seedRequest':{'name':f'{a.workspace}:{name}','srs':{'number':900913},
            'zoomStart':0,'zoomStop':22,'format':'image/png','type':'truncate','threadCount':1}})
        server.request('POST',f'/gwc/rest/seed/{a.workspace}:{name}.json',{'seedRequest':{'name':f'{a.workspace}:{name}','srs':{'number':4326},
            'zoomStart':0,'zoomStop':22,'format':'image/png','type':'truncate','threadCount':1}})
        if shared:
            deadline = time.monotonic()+600
            while True:
                tasks=json.loads(server.request('GET',f'/gwc/rest/seed/{a.workspace}:{name}.json')).get('long-array-array',[])
                if not tasks: break
                if any(len(t)>4 and t[4] in (-1,3) for t in tasks) or time.monotonic()>deadline:
                    raise RuntimeError(f'Cache truncation failed or timed out for {a.workspace}:{name}')
                time.sleep(0.5)
    params={'service':'WMS','version':'1.1.1','request':'GetMap','layers':f'{a.workspace}:{name}','styles':'','srs':'EPSG:4326',
        'bbox':','.join(map(str,manifest.get('preview_bbox',manifest['bbox']))),'width':1000,'height':1000,'format':'image/png'}
    manifest['wms_url']=server.url+'/wms?'+urllib.parse.urlencode(params)
    manifest['wmts_url']=server.url+'/gwc/service/wmts?SERVICE=WMTS&REQUEST=GetCapabilities'
    manifest['workspace']=a.workspace; manifest['group']=name; manifest['cache']=str(gpkg)
    (a.styles/'publication.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(manifest['wms_url']); print(manifest['wmts_url'],flush=True)
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('cell',type=Path,nargs='?'); p.add_argument('--catalogue',type=Path); p.add_argument('--url',default='http://127.0.0.1:18080/geoserver')
    p.add_argument('--user',default=os.environ.get('GEOSERVER_USER','admin'))
    p.add_argument('--password',default=os.environ.get('GEOSERVER_PASSWORD'))
    p.add_argument('--workspace',default='noaa'); p.add_argument('--data-dir',required=True,type=Path)
    p.add_argument('--cache',required=True,type=Path); p.add_argument('--ogr2ogr',required=True,type=Path)
    p.add_argument('--styles',type=Path,default=Path('portrayal/generated'))
    p.add_argument('--palette',choices=['day','dusk','night'],default='day'); p.add_argument('--update',action='store_true')
    p.add_argument('--shallow',type=float,default=2); p.add_argument('--safety',type=float,default=5); p.add_argument('--deep',type=float,default=10)
    publish(p.parse_args())
