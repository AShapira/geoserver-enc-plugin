#!/usr/bin/env python3
"""Capture an initialized, isolated OpenCPN Xvfb reference container.

The chart database must contain only the comparison cell. This does not automate
first-run agreements. See docs/portrayal-comparison.md for setup and provenance.
"""
import argparse
import configparser
import json
import math
from pathlib import Path
import subprocess
import time
import urllib.parse
import urllib.request


def scene(ppm, palette='day', lon=-73.6875, lat=40.6125, cell='US5NY1BH', workspace='reference'):
    width,height=1278,936;k0=.9996;r=6378137
    x=r*math.radians(lon);y=r*math.asinh(math.tan(math.radians(lat)))
    bbox=[x-width/(2*ppm*k0),y-height/(2*ppm*k0),x+width/(2*ppm*k0),y+height/(2*ppm*k0)]
    params={'SERVICE':'WMS','REQUEST':'GetMap','VERSION':'1.1.1','LAYERS':workspace+':chart_'+palette,
            'SRS':'EPSG:3857','BBOX':','.join(map(str,bbox)),'WIDTH':width,'HEIGHT':height,'FORMAT':'image/png','SCALEMETHOD':'Accurate'}
    return {'cell':cell,'center':[lon,lat],'ppm':ppm,'mercator_k0':k0,'width':width,'height':height,
            'bbox3857':bbox,'reference_crop':[1,0,1279,936],
            'wms_url':'http://127.0.0.1:18080/geoserver/wms?'+urllib.parse.urlencode(params)}


def capture(container,out,palette,ppm,lon=-73.6875,lat=40.6125,cell='US5NY1BH',workspace='reference',chart_dir='/charts'):
    def command(*args,**kw): return subprocess.run(['podman','exec',container,*args],check=True,**kw)
    def wait_closed():
        for _ in range(30):
            if subprocess.run(['podman','exec',container,'pgrep','-x','opencpn'],stdout=subprocess.DEVNULL).returncode==1:return
            time.sleep(.5)
        raise RuntimeError('OpenCPN did not finish saving and exiting')
    subprocess.run(['podman','exec',container,'opencpn','-r','-q'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    wait_closed()
    config=subprocess.check_output(['podman','exec',container,'cat','/root/.opencpn/opencpn.conf'],text=True)
    c=configparser.RawConfigParser(strict=False);c.optionxform=str;c.read_string(config)
    c['Settings/GlobalState']['nColorScheme']=str({'day':1,'dusk':2,'night':3}[palette])
    # Keep the own-ship overlay outside the chart comparison.
    c['Settings/GlobalState']['OwnShipLatLon']='"1,1"'
    c['Settings/GlobalState']['bExtendLightSectors']='0'
    c['Settings']['ShowChartBar']='0'
    c['Canvas/CanvasConfig1']['canvasVPScale']=str(ppm)
    c['Canvas/CanvasConfig1']['canvasVPLatLon']=f'"{lat},{lon}"'
    c['ChartDirectories']['ChartDir1']=chart_dir+'^'
    out.mkdir(parents=True,exist_ok=True)
    with (out/'requested.conf').open('w') as f:c.write(f,space_around_delimiters=False)
    subprocess.run(['podman','cp',str(out/'requested.conf'),container+':/root/.opencpn/opencpn.conf'],check=True)
    subprocess.run(['podman','exec','-d',container,'sh','-c','opencpn -G -f -D > /tmp/opencpn.stdout 2>&1'],check=True)
    time.sleep(8)
    command('pgrep','-x','opencpn',stdout=subprocess.DEVNULL)
    # Rebuilding the database deliberately moves own-ship to a chart centroid.
    # Restart once with the saved database and an off-chart own-ship position.
    command('opencpn','-r','-q');wait_closed()
    saved=subprocess.check_output(['podman','exec',container,'cat','/root/.opencpn/opencpn.conf'],text=True)
    c=configparser.RawConfigParser(strict=False);c.optionxform=str;c.read_string(saved)
    c['Settings/GlobalState']['OwnShipLatLon']='"1,1"'
    # Saved config rounds coordinates to four decimals; restore full registration.
    c['Canvas/CanvasConfig1']['canvasVPScale']=str(ppm)
    c['Canvas/CanvasConfig1']['canvasVPLatLon']=f'"{lat},{lon}"'
    with (out/'render-requested.conf').open('w') as f:c.write(f,space_around_delimiters=False)
    subprocess.run(['podman','cp',str(out/'render-requested.conf'),container+':/root/.opencpn/opencpn.conf'],check=True)
    subprocess.run(['podman','exec','-d',container,'sh','-c','opencpn -G -f > /tmp/opencpn.stdout 2>&1'],check=True)
    time.sleep(8);command('pgrep','-x','opencpn',stdout=subprocess.DEVNULL)
    command('xdotool','mousemove','1279','959')
    command('import','-window','root','/tmp/reference.png')
    subprocess.run(['podman','cp',container+':/tmp/reference.png',str(out/'full.png')],check=True)
    command('opencpn','-r','-q');wait_closed()
    subprocess.run(['podman','cp',container+':/root/.opencpn/opencpn.conf',str(out/'actual.conf')],check=True)
    from PIL import Image
    Image.open(out/'full.png').crop((1,0,1279,936)).save(out/'opencpn.png')
    (out/'scene.json').write_text(json.dumps(scene(ppm,palette,lon,lat,cell,workspace),indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--container',default='enc-opencpn-reference')
    p.add_argument('--out',type=Path,required=True);p.add_argument('--palette',choices=['day','dusk','night'],default='day');p.add_argument('--ppm',type=float,default=.15)
    p.add_argument('--lon',type=float,default=-73.6875);p.add_argument('--lat',type=float,default=40.6125)
    p.add_argument('--cell',default='US5NY1BH');p.add_argument('--workspace',default='reference');p.add_argument('--chart-dir',default='/charts')
    a=p.parse_args();capture(a.container,a.out,a.palette,a.ppm,a.lon,a.lat,a.cell,a.workspace,a.chart_dir)
