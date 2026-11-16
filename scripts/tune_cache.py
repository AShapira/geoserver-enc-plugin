#!/usr/bin/env python3
"""Apply bounded demo resource settings and seed an explicit, small WMTS plan.

Default is a read-only plan. --apply updates this dedicated GeoServer instance;
--seed additionally fills only missing tiles and waits for completion.
"""
import argparse
import json
import math
import os
from pathlib import Path
import time
import xml.etree.ElementTree as ET
from publish import Server

REGIONS={'new-york':[-74.06,40.60,-73.94,40.75],'san-francisco':[-122.55,37.74,-122.32,37.88]}
R=6378137


def tile_range(bbox,z):
    west,south,east,north=bbox;n=2**z
    x=lambda lon:(lon+180)/360*n
    y=lambda lat:(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n
    # Inclusive bound is conservative at exact grid boundaries.
    return [math.floor(x(west)),math.floor(y(north)),math.floor(x(east)),math.floor(y(south))]


def plan(regions,minzoom,maxzoom,palettes):
    if not 0<=minzoom<=maxzoom<=18:raise ValueError('Require 0 <= zooms <= 18')
    entries=[];unique=set();metatiles=set()
    for name,bbox in regions.items():
        if not (-180<=bbox[0]<bbox[2]<=180 and -85<=bbox[1]<bbox[3]<=85):raise ValueError('Invalid seed extent')
        for palette in palettes:
            for z in range(minzoom,maxzoom+1):
                x1,y1,x2,y2=tile_range(bbox,z)
                for x in range(x1,x2+1):
                    for y in range(y1,y2+1):unique.add((palette,z,x,y));metatiles.add((palette,z,x//4,y//4))
            entries.append({'region':name,'bbox4326':bbox,'layer':'noaa:chart_'+palette,'minzoom':minzoom,'maxzoom':maxzoom})
    # GWC renders complete 4x4 metatiles including neighbours of requested bounds.
    return {'entries':entries,'requested_tiles':len(unique),'metatiles':len(metatiles),'maximum_generated_tiles':len(metatiles)*16,
            'estimated_bytes_at_100KiB_per_tile':len(metatiles)*16*100*1024}


def run(a):
    regions={k:REGIONS[k] for k in a.regions};p=plan(regions,a.min_zoom,a.max_zoom,a.palettes)
    if p['maximum_generated_tiles']>a.max_tiles:raise ValueError('Seed plan exceeds --max-tiles, including metatile expansion')
    result={'plan':p,'quota_bytes':a.quota_gib*1024**3,'applied':False,'seeded':False}
    def checkpoint():
        if a.report:
            a.report.parent.mkdir(parents=True,exist_ok=True)
            a.report.write_text(json.dumps(result,indent=2)+'\n')
    if not a.apply:
        checkpoint();print(json.dumps(result,indent=2));return result
    if not a.password:raise ValueError('Set GEOSERVER_PASSWORD')
    s=Server(a.url,a.user,a.password)
    quota=ET.fromstring(s.request('GET','/gwc/rest/diskquota.xml'))
    result['previous_quota_xml']=ET.tostring(quota,encoding='unicode')
    def field(root,name,value):
        e=root.find(name)
        if e is None:e=ET.SubElement(root,name)
        e.text=str(value)
    field(quota,'enabled','true');field(quota,'cacheCleanUpFrequency',60);field(quota,'cacheCleanUpUnits','SECONDS')
    field(quota,'maxConcurrentCleanUps',1);field(quota,'globalExpirationPolicyName','LRU')
    q=quota.find('globalQuota')
    if q is None:q=ET.SubElement(quota,'globalQuota')
    for child in list(q):q.remove(child)
    # PUT uses GWC's quota converter; GET in GeoServer 3.0.2 exposes raw bytes.
    field(q,'value',a.quota_gib);field(q,'units','GiB')
    # GWC 2.0.2's quota PUT only mutates its in-memory bean; it does not call
    # saveConfig/reloadConfig. Persist through GeoServer's resource endpoint and
    # reload the dedicated instance so the cleanup scheduler uses this config.
    quota.tag='gwcQuotaConfiguration'
    for node in quota.iter():
        raw=node.find('bytes')
        if raw is not None:
            value=raw.text
            for child in list(node):node.remove(child)
            field(node,'value',value);field(node,'units','B')
    resource='/rest/resource/'+a.quota_resource.lstrip('/')
    payload=ET.tostring(quota)
    s.request('PUT',resource,payload,'application/xml')
    saved=s.request('GET',resource)
    if ET.tostring(ET.fromstring(saved))!=payload:raise RuntimeError('Persisted quota read-back mismatch')
    result['persisted_quota_resource']=resource
    s.request('POST','/rest/reload',b'')
    result['quota_xml']=s.request('GET','/gwc/rest/diskquota.xml').decode()
    confirmed=ET.fromstring(result['quota_xml'])
    confirmed_bytes=confirmed.findtext('globalQuota/bytes')
    if confirmed_bytes is None:
        units={'B':1,'KiB':1024,'MiB':1024**2,'GiB':1024**3}
        confirmed_bytes=float(confirmed.findtext('globalQuota/value'))*units[confirmed.findtext('globalQuota/units')]
    if confirmed.findtext('enabled')!='true' or int(confirmed_bytes)!=result['quota_bytes']:raise RuntimeError('Quota read-back mismatch')
    result['previous_logging']=json.loads(s.request('GET','/rest/logging.json'))
    s.request('PUT','/rest/logging',{'logging':{'level':'PRODUCTION_LOGGING','stdOutLogging':True}})
    result['logging']=json.loads(s.request('GET','/rest/logging.json'))
    # Existing WMS memory estimate multiplies all 168 passes; avoid a low false limit.
    # Concurrency and the container limit provide the memory bound instead.
    s.request('PUT','/rest/services/wms/settings',{'wms':{'maxRenderingTime':120,'maxRenderingErrors':100}})
    result['applied']=True
    for palette in a.palettes:
        path='/gwc/rest/layers/noaa:chart_'+palette+'.xml';layer=ET.fromstring(s.request('GET',path))
        field(layer,'expireCache',604800);field(layer,'expireClients',3600)
        s.request('PUT',path,ET.tostring(layer),'application/xml')
        confirmed=ET.fromstring(s.request('GET',path))
        if confirmed.findtext('expireCache')!='604800' or confirmed.findtext('expireClients')!='3600':raise RuntimeError('Tile expiration read-back mismatch')
    checkpoint()
    if a.seed:
        result['jobs']=[]
        for entry in p['entries']:
            b=entry['bbox4326'];project=lambda lon,lat:(R*math.radians(lon),R*math.asinh(math.tan(math.radians(lat))))
            x1,y1=project(b[0],b[1]);x2,y2=project(b[2],b[3]);layer=entry['layer']
            request={'seedRequest':{'name':layer,'srs':{'number':900913},'bounds':{'coords':{'double':[x1,y1,x2,y2]}},
                'zoomStart':a.min_zoom,'zoomStop':a.max_zoom,'format':'image/png','type':'seed','threadCount':1}}
            # One job at a time; existing unrelated jobs are not killed or replaced.
            start=time.monotonic();s.request('POST','/gwc/rest/seed/'+layer+'.json',request)
            while True:
                state=json.loads(s.request('GET','/gwc/rest/seed/'+layer+'.json'))
                tasks=state.get('long-array-array',[])
                if not tasks:break
                if any(len(t)>4 and t[4] in (-1,3) for t in tasks):raise RuntimeError('Seed task failed or was aborted: '+str(tasks))
                if time.monotonic()-start>a.timeout:raise TimeoutError('Seed timeout; inspect job before cancelling')
                time.sleep(2)
            result['jobs'].append({**entry,'seconds':round(time.monotonic()-start,3)});checkpoint();print('Seeded',entry['region'],layer,flush=True)
        result['seeded']=True
    checkpoint()
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default='http://127.0.0.1:18080/geoserver')
    p.add_argument('--user',default=os.environ.get('GEOSERVER_USER','admin'));p.add_argument('--password',default=os.environ.get('GEOSERVER_PASSWORD'))
    p.add_argument('--apply',action='store_true');p.add_argument('--seed',action='store_true');p.add_argument('--quota-gib',type=int,default=2)
    p.add_argument('--regions',nargs='+',choices=REGIONS,default=list(REGIONS));p.add_argument('--palettes',nargs='+',choices=['day','dusk','night'],default=['day','dusk','night'])
    p.add_argument('--min-zoom',type=int,default=11);p.add_argument('--max-zoom',type=int,default=13);p.add_argument('--max-tiles',type=int,default=2048)
    p.add_argument('--timeout',type=int,default=1800);p.add_argument('--report',type=Path)
    p.add_argument('--quota-resource',default='gwc/geowebcache-diskquota.xml',help='Data-directory resource path; match a custom GWC config directory if used')
    a=p.parse_args()
    if a.seed and not a.apply:p.error('--seed requires --apply')
    if not 1<=a.quota_gib<=16:p.error('--quota-gib must be 1..16')
    run(a)
