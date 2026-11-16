#!/usr/bin/env python3
"""Materialize every indexed cell with the same cache identity as the Java plugin."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import time
from cache_key import snapshot_path


def warm(index,cache,executable,workers=4):
    cache.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(index) as db:
        cells=list(db.execute('SELECT name,path,edition,updn FROM cells ORDER BY name'))
    version=subprocess.check_output([str(executable),'--version'],text=True).strip()
    started=time.monotonic();failures=[];converted=0
    def one(cell):
        name,relative,edition,update=cell
        source=index.parent/relative
        target=snapshot_path(source,cache,executable,version)
        with target.with_suffix('.lock').open('a') as lock:
            fcntl.lockf(lock,fcntl.LOCK_EX)
            if target.exists(): return False
            with tempfile.TemporaryDirectory(prefix='warm-',dir=cache) as directory:
                dest=Path(directory)/'chart.gpkg'
                result=subprocess.run([str(executable),'-f','GPKG',str(dest),str(source),
                    '-oo','UPDATES=APPLY','-oo','SPLIT_MULTIPOINT=ON','-oo','ADD_SOUNDG_DEPTH=ON',
                    '-oo','LNAM_REFS=ON','-oo','LIST_AS_STRING=ON','-unsetFid','-unsetFieldWidth',
                    '-mapFieldType','StringList=String,IntegerList=String','-lco','SPATIAL_INDEX=YES'],
                    stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=300)
                if result.returncode or re.search(r'ERROR \d+:',result.stdout): raise RuntimeError(result.stdout[-3000:])
                with sqlite3.connect(dest) as db:
                    actual=db.execute('SELECT DSID_EDTN,DSID_UPDN FROM DSID').fetchone()
                    if tuple(map(int,actual))!=(edition,update): raise RuntimeError('Applied edition/update mismatch')
                    if db.execute('PRAGMA quick_check').fetchone()[0]!='ok': raise RuntimeError('GeoPackage integrity check failed')
                if target!=snapshot_path(source,cache,executable,version): raise RuntimeError('Source changed during import')
                os.replace(dest,target)
            return True
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(one,c):c[0] for c in cells}
        for i,future in enumerate(as_completed(futures),1):
            try: converted+=int(future.result())
            except Exception as error:
                failures.append({'cell':futures[future],'error':str(error)})
                print('FAILED',futures[future],str(error),flush=True)
            if i%100==0 or i==len(cells): print(f'Validated {i}/{len(cells)}, {converted} imported, {len(failures)} failed, {time.monotonic()-started:.1f}s',flush=True)
    report={'cells':len(cells),'converted':converted,'failures':failures,'gdal':version,'seconds':round(time.monotonic()-started,1)}
    (cache/'warm-report.json').write_text(json.dumps(report,indent=2)+'\n')
    if failures: raise RuntimeError(f'{len(failures)} cells failed conversion')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--catalogue',type=Path,required=True);p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--ogr2ogr',type=Path,default=Path('/usr/bin/ogr2ogr'));p.add_argument('--workers',type=int,default=4)
    a=p.parse_args();warm(a.catalogue,a.cache,a.ogr2ogr,a.workers)
