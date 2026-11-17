#!/usr/bin/env python3
"""Compare saved, registered OpenCPN/GeoServer renders; no conformance claim."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]/'evidence/portrayal'
CASES=['day','detail','dusk','night','sectors','light']


def metrics(reference,candidate,key):
    r=np.asarray(reference.convert('RGB'),dtype=np.int16);c=np.asarray(candidate.convert('RGB'),dtype=np.int16)
    assert r.shape==c.shape
    mask=np.ones(r.shape[:2],dtype=bool)
    # Fixed exclusions for OpenCPN controls, scale bar, chart edge and status UI.
    mask[:60,:]=False;mask[-60:,:]=False;mask[:,:20]=False;mask[:,-20:]=False
    if key=='sectors': mask[:,650:]=False # Outside the ENC: OpenCPN global basemap vs WMS background.
    d=np.abs(r-c);flat=np.ones_like(mask)
    for dy,dx in [(0,3),(0,-3),(3,0),(-3,0)]: flat &= np.max(np.abs(r-np.roll(r,(dy,dx),(0,1))),axis=2)<=2
    flat &= mask
    magenta=lambda a: (a[:,:,0]>140)&(a[:,:,2]>120)&(a[:,:,1]<120)&mask
    return {'pixels_compared':int(mask.sum()),'rgb_mean_absolute_error_0_255':round(float(d[mask].mean()),3),
            'within_12_each_channel_percent':round(float((d.max(axis=2)[mask]<=12).mean()*100),3),
            'reference_flat_area_pixels':int(flat.sum()),'flat_area_within_12_percent':round(float((d.max(axis=2)[flat]<=12).mean()*100),3),
            'reference_magenta_pixels':int(magenta(r).sum()),'candidate_magenta_pixels':int(magenta(c).sum())}


def run(root=ROOT):
    results={}
    cases=CASES+(['quality'] if (root/'reference-quality/scene.json').exists() else [])
    for key in cases:
        reference=Image.open(root/f'reference-{key}/opencpn.png')
        scene=json.loads((root/f'reference-{key}/scene.json').read_text())
        entry={'scene':scene,'after':metrics(reference,Image.open(root/f'after/{key}.png'),key)}
        before=root/f'before/{key}.png'
        if before.exists(): entry['before']=metrics(reference,Image.open(before),key)
        results[key]=entry
    (root/'comparison.json').write_text(json.dumps(results,indent=2)+'\n')
    html='''<!doctype html><meta charset="utf-8"><title>NOAA ENC portrayal comparison</title>
<style>body{font:16px system-ui;margin:24px;background:#15202b;color:#edf2f7}a{color:#9ed6ff}select,input,button{font:inherit}#view{position:relative;max-width:1278px;aspect-ratio:1278/936}#view img{position:absolute;width:100%;height:100%;inset:0}#revision{clip-path:inset(0 0 0 50%)}#split{width:min(100%,1278px)}pre{white-space:pre-wrap}label{margin-right:20px}</style>
<h1>NOAA ENC · OpenCPN versus GeoServer</h1>
<p>Actual OpenCPN 5.12.4 screenshots and WMS renders of identical NOAA cells. Left: OpenCPN. Right: revised GeoServer. Drag to compare.</p>
<p><label>Scene <select id="scene"><option value="day">New York · day</option><option value="detail">New York · soundings detail</option><option value="dusk">New York · dusk</option><option value="night">New York · night</option><option value="sectors">San Clemente · extinguished light</option><option value="light">Humboldt Bay · sector lights</option>QUALITY_OPTION</select></label><button id="baseline">Show before</button></p>
<input id="split" type="range" min="0" max="100" value="50" aria-label="Comparison split">
<div id="view"><img id="reference" alt="OpenCPN reference"><img id="revision" alt="GeoServer render"></div>
<p id="links"></p><pre id="numbers"></pre>
<p>Metrics exclude fixed viewer controls and outer margins. The San Clemente comparison also excludes the area outside the ENC. They measure this screenshot corpus, not S-52 compliance. Differences remain in labels, complex-line placement, quality procedures and isolated dangers. The revised renderer implements restriction and safety-contour priorities; some safety/quality choices intentionally differ from OpenCPN.</p>
<p><a href="comparison.json">Full measurements and WMS requests</a> · <a href="../../docs/portrayal-comparison.md">Method and limitations</a></p>
<script>const data=DATA;let before=false;const scene=document.querySelector('#scene'),rev=document.querySelector('#revision'),ref=document.querySelector('#reference');function show(){const k=scene.value;before=before&&!!data[k].before;ref.src=`reference-${k}/opencpn.png`;rev.src=`${before?'before':'after'}/${k}.png`;document.querySelector('#baseline').disabled=!data[k].before;document.querySelector('#baseline').textContent=before?'Show revised':'Show before';document.querySelector('#numbers').textContent=JSON.stringify({cell:data[k].scene.cell,view:before?'before':'revised',metrics:data[k][before?'before':'after']},null,2);document.querySelector('#links').innerHTML=`<a href="${ref.src}">Full OpenCPN image</a> · <a href="${rev.src}">Full GeoServer image</a>`;}scene.onchange=show;document.querySelector('#baseline').onclick=()=>{before=!before;show()};document.querySelector('#split').oninput=e=>{rev.style.clipPath=`inset(0 0 0 ${e.target.value}%)`};show();</script>'''.replace('DATA',json.dumps(results))
    html=html.replace('QUALITY_OPTION','<option value="quality">San Clemente · quality close-up (overscaled)</option>' if 'quality' in results else '')
    (root/'comparison.html').write_text(html)
    print(json.dumps({k:{v:m for v,m in d.items() if v!='scene'} for k,d in results.items()},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=ROOT)
    run(parser.parse_args().root)
