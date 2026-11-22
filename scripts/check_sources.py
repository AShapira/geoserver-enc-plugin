#!/usr/bin/env python3
"""Check one covered view per published ENC workspace in WMS and cached WMTS."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from catalogue_smoke import fetch


def check(root, workspace, view, out):
    lon, lat, zoom = view
    n = 2**zoom
    col = int((lon+180)/360*n)
    row = int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n)
    dx = 360/n
    dy = dx*math.cos(math.radians(lat))
    bounds = [lon-dx, lat-dy, lon+dx, lat+dy]
    results = {}
    for palette in ('day','dusk','night'):
        group = workspace + ':chart_' + palette
        wms = root+'/wms?'+urlencode(dict(service='WMS',version='1.1.1',request='GetMap',
            layers=group,styles='',srs='EPSG:4326',bbox=','.join(map(str,bounds)),
            width=512,height=512,format='image/png'))
        wmts = root+'/gwc/service/wmts?'+urlencode(dict(service='WMTS',version='1.0.0',request='GetTile',
            layer=group,style='',format='image/png',tilematrixset='EPSG:900913',
            tilematrix=f'EPSG:900913:{zoom}',tilecol=col,tilerow=row))
        image,_,_ = fetch(wms,(512,512))
        tile,_,_ = fetch(wmts,(256,256))
        again,headers,_ = fetch(wmts,(256,256))
        if again != tile or headers.get('geowebcache-cache-result') != 'HIT':
            raise ValueError(f'{group}: repeated tile was not a cache hit')
        results[palette] = {'wms_sha256':hashlib.sha256(image).hexdigest(),
                            'wmts_sha256':hashlib.sha256(tile).hexdigest(),'repeat':'HIT'}
        if out:
            (out/f'{workspace}-{palette}.png').write_bytes(image)
        print(f'{group}: WMS {len(image)} bytes, WMTS {len(tile)} bytes, HIT',flush=True)
    for key in ('wms_sha256','wmts_sha256'):
        if len({r[key] for r in results.values()}) != 3:
            raise ValueError(f'{workspace}: palettes produced identical images')
    return {'view':view,'palettes':results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:18080/geoserver')
    parser.add_argument('--workspace',action='append')
    parser.add_argument('--out',type=Path)
    args = parser.parse_args()
    if args.out: args.out.mkdir(parents=True,exist_ok=True)
    with urlopen(args.url+'/www/enc-sources.json') as response:
        registry=json.load(response)
    results={ws:check(args.url,ws,registry[ws]['view'],args.out) for ws in args.workspace or sorted(registry)}
    if args.out: (args.out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
