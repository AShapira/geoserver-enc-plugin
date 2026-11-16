#!/usr/bin/env python3
"""Measure live ENC request latency and Linux container resource deltas.

Samples cgroup v2 and Java RSS; percentages are relative to one CPU core.
Does not clear OS caches, truncate tiles or modify the service configuration.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid

SAMPLER = r'''
import json,time,os,sys
from pathlib import Path
Path(sys.argv[1]).write_text(str(os.getpid()))
def pairs(path):
    return {a:int(b) for a,b,*_ in (x.replace(':','').split() for x in Path(path).read_text().splitlines()) if b.isdigit()}
deadline=time.monotonic()+1800
while time.monotonic()<deadline:
    c=pairs('/sys/fs/cgroup/cpu.stat');m=pairs('/sys/fs/cgroup/memory.stat');p=pairs('/proc/1/status');io=pairs('/proc/1/io')
    print(json.dumps({'t':time.time(),'cpu_us':c['usage_usec'],'memory':int(Path('/sys/fs/cgroup/memory.current').read_text()),'anon':m['anon'],'file':m['file'],'rss':p['VmRSS']*1024,'read_bytes':io['read_bytes'],'write_bytes':io['write_bytes'],'rchar':io['rchar']}),flush=True)
    time.sleep(.25)
'''


def run(a):
    a.out.mkdir(parents=True,exist_ok=True)
    samples=[]
    pidfile='/tmp/enc-benchmark-'+uuid.uuid4().hex+'.pid'
    process=subprocess.Popen([a.engine,'exec',a.container,'python3','-u','-c',SAMPLER,pidfile],stdout=subprocess.PIPE,text=True)
    def read():
        for line in process.stdout: samples.append(json.loads(line))
    thread=threading.Thread(target=read,daemon=True);thread.start()
    deadline=time.monotonic()+15
    while not samples:
        if process.poll() is not None or time.monotonic()>deadline: raise RuntimeError('Container sampler did not start')
        time.sleep(.1)
    base=a.url.rstrip('/')
    def wms(bbox):
        return base+'/wms?'+urllib.parse.urlencode({'SERVICE':'WMS','REQUEST':'GetMap','VERSION':'1.1.1','LAYERS':a.layer,'SRS':'EPSG:4326','BBOX':bbox,'WIDTH':1000,'HEIGHT':800,'FORMAT':'image/png'})
    urls={'new_york':wms('-74.06,40.60,-73.94,40.75'),
          'san_francisco':wms('-122.55,37.74,-122.32,37.88'),
          'overview':wms('-130,22,-60,52'),
          'wmts':base+'/gwc/service/wmts?'+urllib.parse.urlencode({'SERVICE':'WMTS','REQUEST':'GetTile','VERSION':'1.0.0','LAYER':a.layer,'STYLE':'','FORMAT':'image/png','TILEMATRIXSET':'EPSG:900913','TILEMATRIX':'EPSG:900913:13','TILEROW':3080,'TILECOL':2411})}
    if a.miss_probe:
        urls['wmts_unseeded']=base+'/gwc/service/wmts?'+urllib.parse.urlencode({'SERVICE':'WMTS','REQUEST':'GetTile','VERSION':'1.0.0','LAYER':a.layer,'STYLE':'','FORMAT':'image/png','TILEMATRIXSET':'EPSG:900913','TILEMATRIX':'EPSG:900913:14','TILEROW':6160,'TILECOL':4822})
    def request(url):
        start=time.monotonic()
        with urllib.request.urlopen(url,timeout=180) as response:
            data=response.read();headers=dict(response.headers)
        if not data.startswith(b'\x89PNG'):raise RuntimeError(data[:1000])
        return {'seconds':time.monotonic()-start,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'cache':headers.get('geowebcache-cache-result')}
    result={'recorded_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'container':a.container,'layer':a.layer,'sample_period_seconds':.25,'cpu_percent_basis':'100 percent = one CPU core','cases':{}}
    try:
        start=time.time();time.sleep(3)
        idle=[s for s in samples if s['t']>=start]
        result['idle']={'cpu_percent':(idle[-1]['cpu_us']-idle[0]['cpu_us'])/1e4/(idle[-1]['t']-idle[0]['t']),'memory_bytes':idle[-1]['memory'],'rss_bytes':idle[-1]['rss'],'anon_bytes':idle[-1]['anon'],'file_cache_bytes':idle[-1]['file']}
        for name,url in urls.items():
            initial_before=samples[-1]
            first=request(url)
            time.sleep(.3);initial_after=samples[-1]
            first['cpu_seconds_in_sample_window']=(initial_after['cpu_us']-initial_before['cpu_us'])/1e6
            first['sample_window_seconds']=initial_after['t']-initial_before['t']
            # Separate warm-up/JIT and initial tile status from measured repetitions.
            before=samples[-1];begin=time.monotonic()
            calls=[request(url) for _ in range(max(100,a.repeat) if name.startswith('wmts') else a.repeat)]
            elapsed=time.monotonic()-begin;time.sleep(.3);after=samples[-1]
            period=[s for s in samples if before['t']<=s['t']<=after['t']]
            entry={'url':url,'initial':first,'requests':calls,'median_seconds':statistics.median(c['seconds'] for c in calls),'wall_seconds':elapsed,'cpu_seconds':(after['cpu_us']-before['cpu_us'])/1e6,'peak_memory_bytes':max(s['memory'] for s in period),'peak_rss_bytes':max(s['rss'] for s in period),'peak_anon_bytes':max(s['anon'] for s in period),'peak_file_cache_bytes':max(s['file'] for s in period),'physical_read_bytes':after['read_bytes']-before['read_bytes'],'logical_read_bytes':after['rchar']-before['rchar'],'write_bytes':after['write_bytes']-before['write_bytes']}
            entry['sample_window_seconds']=after['t']-before['t']
            entry['cpu_percent']=entry['cpu_seconds']/entry['sample_window_seconds']*100
            result['cases'][name]=entry
            print(name,round(entry['median_seconds'],3),'s median;',round(entry['cpu_percent'],1),'% CPU',flush=True)
        before=samples[-1];begin=time.monotonic()
        with ThreadPoolExecutor(max_workers=4) as pool: calls=list(pool.map(request,[urls['new_york']]*4))
        elapsed=time.monotonic()-begin;time.sleep(.3);after=samples[-1]
        result['concurrent_four_wms']={'requests':calls,'wall_seconds':elapsed,'requests_per_second':4/elapsed,'cpu_seconds':(after['cpu_us']-before['cpu_us'])/1e6,'peak_memory_bytes':max(s['memory'] for s in samples if s['t']>=before['t']),'identical_images':len({c['sha256'] for c in calls})==1}
        if a.sustained_requests:
            before=samples[-1];begin=time.monotonic()
            with ThreadPoolExecutor(max_workers=a.concurrency) as pool:
                calls=list(pool.map(request,[urls['new_york']]*a.sustained_requests))
            elapsed=time.monotonic()-begin;time.sleep(.3);after=samples[-1]
            ordered=sorted(c['seconds'] for c in calls)
            result['sustained_wms']={'concurrency':a.concurrency,'count':len(calls),'requests':calls,'wall_seconds':elapsed,
                'median_seconds':statistics.median(ordered),'p95_seconds':ordered[max(0,__import__('math').ceil(.95*len(ordered))-1)],
                'requests_per_second':len(calls)/elapsed,'cpu_seconds':(after['cpu_us']-before['cpu_us'])/1e6,
                'peak_memory_bytes':max(s['memory'] for s in samples if s['t']>=before['t']),
                'peak_rss_bytes':max(s['rss'] for s in samples if s['t']>=before['t']),
                'identical_images':len({c['sha256'] for c in calls})==1}
            print('sustained',a.concurrency,'clients',len(calls),'requests p95',round(result['sustained_wms']['p95_seconds'],3),flush=True)
        for command,label in [(['jcmd','1','GC.heap_info'],'heap'),(['jcmd','1','VM.flags'],'jvm_flags'),(['du','-sk','/opt/enc-data','/opt/enc-cache','/opt/geoserver_data'],'disk_kib')]:
            result[label]=subprocess.check_output([a.engine,'exec',a.container,*command],text=True).strip()
        (a.out/'results.json').write_text(json.dumps(result,indent=2)+'\n')
        (a.out/'samples.json').write_text(json.dumps(samples)+'\n')
    finally:
        # Killing the local podman client alone leaves the sampler alive inside the container.
        subprocess.run([a.engine,'exec',a.container,'python3','-c',
            'import os,signal,sys;from pathlib import Path;p=Path(sys.argv[1]);pid=int(p.read_text());p.unlink();os.kill(pid,signal.SIGTERM)',pidfile],check=False)
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--engine',default='podman');p.add_argument('--container',default='geoserver-enc')
    p.add_argument('--url',default='http://127.0.0.1:18080/geoserver');p.add_argument('--layer',default='noaa:chart_day');p.add_argument('--repeat',type=int,default=3);p.add_argument('--out',required=True,type=Path)
    p.add_argument('--sustained-requests',type=int,default=0);p.add_argument('--concurrency',type=int,default=8)
    p.add_argument('--miss-probe',action='store_true',help='Probe an unseeded zoom-14 tile; report actual MISS/HIT header')
    run(p.parse_args())
