#!/usr/bin/env python3
"""Exercise a clean installation with NOAA US5NY1AI and its adjacent .001 update."""
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import xml.etree.ElementTree as ET
import sqlite3
from urllib.parse import urlencode

from PIL import Image
from urllib.request import build_opener, HTTPCookieProcessor, urlopen
from http.cookiejar import CookieJar

from publish import Server


def image(url):
    with urlopen(url, timeout=120) as response:
        content = response.read()
        cache_result = response.headers.get('geowebcache-cache-result')
    with Image.open(io.BytesIO(content)) as im:
        if im.size != (256, 256) or len(im.convert('RGB').getcolors(65536)) < 2:
            raise ValueError('Expected visible depth-area features')
    return hashlib.sha256(content).hexdigest(), cache_result


def check(args):
    auth = (os.environ.get('GEOSERVER_USER', 'admin'), os.environ['GEOSERVER_PASSWORD'])
    api = Server(args.url, *auth)
    session = build_opener(HTTPCookieProcessor(CookieJar()))
    session.open(args.url + '/web/', timeout=60).close()
    login = urlencode({'username': auth[0], 'password': auth[1]}).encode()
    session.open(args.url + '/j_spring_security_check', login, timeout=60).close()
    with session.open(args.url + '/web/wicket/bookmarkable/org.geoserver.web.data.store.NewDataPage', timeout=60) as page:
        store_listed = b'S-57 ENC (GDAL)' in page.read()
    if not store_listed:
        raise RuntimeError('Web UI did not list the S-57 store')
    ws = '/rest/workspaces/enc_check'
    if args.publish:
        if not api.exists(ws + '.json'):
            api.request('POST', '/rest/workspaces', {'workspace':{'name':'enc_check'}})
        settings = {'dbtype':'s57', 'file':args.cell, 'cache':args.cache, 'ogr2ogr':'/usr/bin/ogr2ogr'}
        store = ws + '/datastores/chart'
        if not api.exists(store + '.json'):
            api.request('POST', ws+'/datastores', {'dataStore':{'name':'chart', 'connectionParameters':settings}})
        if not api.exists(store+'/featuretypes/DEPARE.json'):
            api.request('POST', store+'/featuretypes', {'featureType':{'name':'DEPARE','nativeName':'DEPARE','srs':'EPSG:4326'}})
        api.request('PUT', '/rest/layers/enc_check:DEPARE', {'layer':{'defaultStyle':{'name':'enc_v1_day_DEPARE'}}})
        tiles = '/gwc/rest/layers/enc_check:DEPARE.xml'
        if not api.exists(tiles):
            api.request('PUT', tiles, b'<GeoServerLayer><name>enc_check:DEPARE</name><enabled>true</enabled>'
                        b'<mimeFormats><string>image/png</string></mimeFormats><gridSubsets><gridSubset>'
                        b'<gridSetName>EPSG:900913</gridSetName></gridSubset></gridSubsets></GeoServerLayer>',
                        'application/xml')
    viewer = args.url.rstrip('/') + '/enc/viewer/index.html'
    with urlopen(viewer, timeout=60) as response:
        if b'<title>ENC viewer and search demo</title>' not in response.read():
            raise ValueError('Packaged ENC viewer missing')
    with urlopen(args.url+'/wms?service=WMS&version=1.3.0&request=GetCapabilities&encDiscovery=true',
                 timeout=120) as response:
        capabilities = ET.parse(response)
    visible = [el.findtext('{*}Name') for el in capabilities.findall('.//{*}Layer')
               if el.get('{urn:geoserver:enc:viewer:1}kind') == 'layer']
    if 'enc_check:DEPARE' not in visible:
        raise ValueError('Published S-57 feature type missing from viewer discovery')
    styles = json.loads(api.request('GET','/rest/styles.json'))['styles']['style']
    count = sum(s['name'].startswith('enc_v1_') for s in styles)
    if count != 1530:
        raise RuntimeError(f'Expected 1530 global ENC styles, got {count}')
    params = dict(service='WFS',version='2.0.0',request='GetFeature',typeNames='enc_check:DEPARE',
                  outputFormat='application/json',count=2)
    with urlopen(args.url+'/wfs?' + urlencode(params), timeout=120) as response:
        features = json.load(response)['features']
    if len(features) != 2 or 'DRVAL1' not in features[0]['properties']:
        raise ValueError('Expected two depth areas with depth attributes')
    query = '/wms?'+urlencode(dict(service='WMS',version='1.1.1',request='GetMap',layers='enc_check:DEPARE',
        styles='', srs='EPSG:4326',bbox='-73.65,40.5,-73.575,40.575',width=256,height=256,format='image/png'))
    digest, _ = image(args.url+query)
    z = 12
    col = int((180-73.615)/360*2**z)
    row = int((1-math.asinh(math.tan(math.radians(40.54)))/math.pi)/2*2**z)
    tile = args.url+'/gwc/service/wmts?'+urlencode(dict(service='WMTS',version='1.0.0',request='GetTile',
        layer='enc_check:DEPARE',style='',tilematrixset='EPSG:900913',tilematrix=f'EPSG:900913:{z}',
        tilecol=col,tilerow=row,format='image/png'))
    tilehash, first = image(tile)
    repeated, second = image(tile)
    if repeated != tilehash or second != 'HIT':
        raise ValueError(f'WMTS cache check failed ({first}, {second})')
    if args.cache_files:
        versions = []
        for path in args.cache_files.glob('*.gpkg'):
            with sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True) as db:
                versions.extend(db.execute('SELECT DSID_UPDN FROM DSID').fetchall())
        if not any(int(row[0]) == 1 for row in versions):
            raise ValueError('Could not verify numbered update 1 in served snapshots')
    print(json.dumps(dict(viewer=viewer, styles=count, features=len(features), wms_sha256=digest, wms_query=query,
                          tile_sha256=tilehash, first_tile=first, repeat_tile=second,
                          update_checked=bool(args.cache_files)), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--cell', default='/charts/US5NY1AI.000')
    parser.add_argument('--cache', default='/enc-cache')
    parser.add_argument('--cache-files', type=Path)
    check(parser.parse_args())
