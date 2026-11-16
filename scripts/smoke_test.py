#!/usr/bin/env python3
"""Exercise a running publication through WMS, WFS and cached WMTS requests."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from PIL import Image


def get(url):
    with urllib.request.urlopen(url,timeout=120) as response:
        return response.read(),dict(response.headers)


def png(url,size):
    data,headers=get(url)
    assert data.startswith(b'\x89PNG'),data[:2000]
    image=Image.open(BytesIO(data)); image.load()
    assert image.size==size,(image.size,size)
    assert len(image.convert('RGB').getcolors(image.width*image.height))>8,'Blank or trivial map'
    return data,headers


def run(publication,out):
    m=json.loads(publication.read_text());out.mkdir(parents=True,exist_ok=True)
    root=m['wms_url'].split('/wms?')[0]
    layer=m['workspace']+':'+m['group']
    base=dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(m['wms_url']).query,keep_blank_values=True))
    base.update(width='1000',height='1000')
    url=lambda params: root+'/wms?'+urllib.parse.urlencode(params)
    start=time.monotonic();image,_=png(url(base),(1000,1000)); wms_seconds=time.monotonic()-start
    (out/'wms-overview.png').write_bytes(image)
    x1,y1,x2,y2=m['bbox']
    axis={**base,'version':'1.3.0','crs':'EPSG:4326','bbox':f'{y1},{x1},{y2},{x2}'};axis.pop('srs')
    image13,_=png(url(axis),(1000,1000))
    assert Image.open(BytesIO(image)).tobytes()==Image.open(BytesIO(image13)).tobytes(),'WMS axis order mismatch'
    def mercator(x,y): return (x*20037508.342789244/180,6378137*math.log(math.tan(math.pi/4+math.radians(y)/2)))
    a,b=mercator(x1,y1),mercator(x2,y2)
    projection={**base,'srs':'EPSG:3857','bbox':','.join(map(str,(*a,*b)))}
    projected,_=png(url(projection),(1000,1000));(out/'wms-3857.png').write_bytes(projected)
    # Zoom to soundings and aid-to-navigation detail, preserving the ENC cell boundary.
    cx,cy=(x1+x2)/2,(y1+y2)/2;dx,dy=(x2-x1)/5,(y2-y1)/5
    detail={**base,'bbox':f'{cx-dx},{cy-dy},{cx+dx},{cy+dy}'}
    detailed,_=png(url(detail),(1000,1000));(out/'wms-detail.png').write_bytes(detailed)
    with ThreadPoolExecutor(max_workers=4) as pool:
        concurrent=list(pool.map(lambda _:png(url(base),(1000,1000))[0],range(4)))
    assert all(d==image for d in concurrent),'Concurrent WMS renders differ'
    capabilities,_=get(m['wmts_url']);(out/'wmts-capabilities.xml').write_bytes(capabilities)
    ns={'w':'http://www.opengis.net/wmts/1.0','o':'http://www.opengis.net/ows/1.1'}
    tree=ET.fromstring(capabilities)
    advertised=next(l for l in tree.findall('.//w:Layer',ns) if l.findtext('o:Identifier','',ns)==layer)
    style=advertised.findtext('w:Style/o:Identifier','',ns)
    z=14;n=2**z
    col=int((cx+180)/360*n)
    row=int((1-math.asinh(math.tan(math.radians(cy)))/math.pi)/2*n)
    params={'SERVICE':'WMTS','REQUEST':'GetTile','VERSION':'1.0.0','LAYER':layer,'STYLE':style,'FORMAT':'image/png',
            'TILEMATRIXSET':'EPSG:900913','TILEMATRIX':f'EPSG:900913:{z}','TILEROW':row,'TILECOL':col}
    tileurl=root+'/gwc/service/wmts?'+urllib.parse.urlencode(params)
    tile,first=png(tileurl,(256,256));cached,second=png(tileurl,(256,256))
    assert tile==cached,'Repeated WMTS tile differs'
    assert any(k.lower()=='geowebcache-cache-result' and v=='HIT' for k,v in second.items()),second
    (out/'wmts-tile.png').write_bytes(tile)
    wfs=root+'/ows?'+urllib.parse.urlencode({'service':'WFS','version':'2.0.0','request':'GetFeature','typeNames':m['workspace']+':SOUNDG','count':5,'outputFormat':'application/json'})
    features=json.loads(get(wfs)[0]);assert len(features['features'])==5
    assert all('DEPTH' in f['properties'] and f['geometry']['type']=='Point' for f in features['features'])
    report={'layer':layer,'bbox':m['bbox'],'wms_overview_seconds':round(wms_seconds,3),'wms_1_1_1_vs_1_3_0_pixels_equal':True,
        'wms_3857':True,'concurrent_wms_requests':4,'wmts_tile_url':tileurl,'wmts_first_headers':first,'wmts_second_headers':second,
        'wfs_split_soundings':5,'wms_sha256':hashlib.sha256(image).hexdigest(),'wmts_sha256':hashlib.sha256(tile).hexdigest()}
    (out/'smoke.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if not k.endswith('headers')},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--publication',type=Path,default=Path('portrayal/generated/publication.json'))
    p.add_argument('--out',type=Path,default=Path('evidence'));a=p.parse_args();run(a.publication,a.out)
