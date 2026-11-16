#!/usr/bin/env python3
"""Publish a cell through the S-57 plugin, compile SLDs, and create a WMTS chart group.
Requires local access to the server data directory for symbol assets.
"""
import argparse
import base64
import json
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
    title=a.cell.stem if a.cell else 'Full NOAA catalogue'
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
    target=a.data_dir/'workspaces'/a.workspace/'styles'/'symbols'
    target.mkdir(parents=True,exist_ok=True)
    for asset in (a.styles/'symbols').glob('*.png'): shutil.copy2(asset,target/asset.name)
    styles={v['style'] for v in manifest['layers'].values()}|{v['style'] for v in manifest['stack']}
    for name in sorted(styles):
        path=ws+'/styles/'+name
        data=(a.styles/f'{name}.sld').read_bytes()
        if server.exists(path+'.json'): server.request('PUT',path,data,'application/vnd.ogc.sld+xml')
        else: server.request('POST',ws+'/styles?name='+name,data,'application/vnd.ogc.sld+xml')
    for cls,info in manifest['layers'].items():
        ft=store+'/featuretypes/'+cls
        if not server.exists(ft+'.json'):
            server.request('POST',store+'/featuretypes',{'featureType':{'name':cls,'nativeName':cls,'title':f'{title} — {cls}',
                'srs':'EPSG:4326','projectionPolicy':'FORCE_DECLARED','enabled':True,
                'nativeBoundingBox':{'minx':manifest['bbox'][0],'miny':manifest['bbox'][1],'maxx':manifest['bbox'][2],'maxy':manifest['bbox'][3],'crs':'EPSG:4326'},
                'latLonBoundingBox':{'minx':manifest['bbox'][0],'miny':manifest['bbox'][1],'maxx':manifest['bbox'][2],'maxy':manifest['bbox'][3],'crs':'EPSG:4326'}}})
        server.request('PUT',f'/rest/layers/{a.workspace}:{cls}',{'layer':{'defaultStyle':{'name':f'{a.workspace}:{info["style"]}'},'enabled':True}})
    name='chart_'+a.palette
    stack=manifest['stack']; x1,y1,x2,y2=manifest['bbox']
    group={'layerGroup':{'name':name,'mode':'SINGLE','title':f'{title} ENC ({a.palette})',
        'abstractTxt':'GDAL S-57 with S-52-derived portrayal. Experimental; see portrayal limitations.',
        'publishables':{'published':[{'@type':'layer','name':f'{a.workspace}:{e["class"]}'} for e in stack]},
        'styles':{'style':[{'name':f'{a.workspace}:{e["style"]}'} for e in stack]},
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
    params={'service':'WMS','version':'1.1.1','request':'GetMap','layers':f'{a.workspace}:{name}','styles':'','srs':'EPSG:4326',
        'bbox':','.join(map(str,manifest.get('preview_bbox',manifest['bbox']))),'width':1000,'height':1000,'format':'image/png'}
    manifest['wms_url']=server.url+'/wms?'+urllib.parse.urlencode(params)
    manifest['wmts_url']=server.url+'/gwc/service/wmts?SERVICE=WMTS&REQUEST=GetCapabilities'
    manifest['workspace']=a.workspace; manifest['group']=name; manifest['cache']=str(gpkg)
    (a.styles/'publication.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(manifest['wms_url']); print(manifest['wmts_url'])


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
