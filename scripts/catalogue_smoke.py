#!/usr/bin/env python3
"""Live multi-region tests for the full-catalogue service."""
import argparse
from io import BytesIO
import json
import math
from pathlib import Path
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from PIL import Image

REGIONS={'new-york':[-74.06,40.60,-73.94,40.75], 'san-francisco':[-122.55,37.74,-122.32,37.88],
         'chesapeake':[-76.50,36.88,-76.20,37.12], 'chicago':[-87.68,41.77,-87.48,41.97],
         'seattle':[-122.48,47.52,-122.28,47.72], 'alaska':[-150.13,61.10,-149.75,61.35],
         'hawaii':[-157.97,21.24,-157.79,21.39], 'guam':[144.59,13.38,144.75,13.53],
         'overview':[-130,22,-60,52]}


def fetch(url,size):
    begin=time.monotonic()
    with urllib.request.urlopen(url,timeout=180) as response:
        data=response.read();headers=dict(response.headers)
    assert data.startswith(b'\x89PNG'),data[:1800]
    image=Image.open(BytesIO(data)).convert('RGB');image.load()
    assert image.size==size
    assert len(image.getcolors(size[0]*size[1]))>10,'Blank chart'
    return data,headers,round(time.monotonic()-begin,3)


def run(root,out):
    out.mkdir(parents=True,exist_ok=True);results={}
    for region,bbox in REGIONS.items():
        params={'SERVICE':'WMS','REQUEST':'GetMap','VERSION':'1.1.1','LAYERS':'noaa:chart_day','STYLES':'',
            'SRS':'EPSG:4326','BBOX':','.join(map(str,bbox)),'WIDTH':800,'HEIGHT':600,'FORMAT':'image/png'}
        url=root+'/wms?'+urllib.parse.urlencode(params)
        data,headers,seconds=fetch(url,(800,600));(out/(region+'.png')).write_bytes(data)
        results[region]={'bbox':bbox,'wms_seconds':seconds,'png_bytes':len(data)}
        print(region,seconds,'seconds',len(data),'bytes',flush=True)
    for palette in ['day','dusk','night']:
        z=13;cx,cy=-74.01,40.69;n=2**z
        params={'SERVICE':'WMTS','REQUEST':'GetTile','VERSION':'1.0.0','LAYER':'noaa:chart_'+palette,'STYLE':'','FORMAT':'image/png',
            'TILEMATRIXSET':'EPSG:900913','TILEMATRIX':f'EPSG:900913:{z}','TILEROW':int((1-math.asinh(math.tan(math.radians(cy)))/math.pi)/2*n),'TILECOL':int((cx+180)/360*n)}
        url=root+'/gwc/service/wmts?'+urllib.parse.urlencode(params)
        a,first,seconds=fetch(url,(256,256));b,second,_=fetch(url,(256,256));assert a==b
        assert second.get('geowebcache-cache-result')=='HIT',second
        (out/('wmts-'+palette+'.png')).write_bytes(a)
        results['wmts-'+palette]={'url':url,'first_seconds':seconds,'second_result':second.get('geowebcache-cache-result')}
        print('WMTS',palette,'cache HIT',flush=True)
    bbox=REGIONS['new-york']
    p={'SERVICE':'WMS','REQUEST':'GetMap','VERSION':'1.3.0','LAYERS':'noaa:chart_day','CRS':'EPSG:4326',
       'BBOX':','.join(map(str,[bbox[1],bbox[0],bbox[3],bbox[2]])),'WIDTH':800,'HEIGHT':600,'FORMAT':'image/png'}
    data,_,_=fetch(root+'/wms?'+urllib.parse.urlencode(p),(800,600))
    assert Image.open(BytesIO(data)).tobytes()==Image.open(out/'new-york.png').tobytes()
    results['wms_axis_order_equal']=True
    (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default='http://127.0.0.1:18080/geoserver');p.add_argument('--out',type=Path,default=Path('evidence/catalogue'))
    a=p.parse_args();run(a.url.rstrip('/'),a.out)
