#!/usr/bin/env python3
"""Read-only audit of every expected sidecar against the immutable NOAA catalogue."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import time
from cache_key import snapshot_path


def audit(catalogue,cache,ogr2ogr,out):
    started=time.monotonic()
    xml=Path(__file__).resolve().parents[1]/'portrayal/upstream/chartsymbols.xml'
    revision=hashlib.sha256(b'enc-edges-2:lookup-4:inland-classes'+xml.read_bytes()).hexdigest()[:16]
    version=subprocess.check_output([str(ogr2ogr),'--version'],text=True).strip()
    totals=dict(cells=0,edges=0,features=0,links=0,point_quality=0,masked_links=0,quality_edges=0,unreliable_edges=0,unreliable_point_primitives=0,conditional_restrictions=0,contour_candidates=0,unmatched_lookups=0,bytes=0)
    edge_quality={};point_quality={}
    unknown={};errors=[]
    with sqlite3.connect(f'file:{catalogue.resolve()}?mode=ro',uri=True) as index:
        cells=index.execute('SELECT name,path FROM cells ORDER BY name').fetchall()
    for name,path in cells:
        try:
            snapshot=snapshot_path(catalogue.parent/path,cache,ogr2ogr,version)
            sidecar=snapshot.with_name(snapshot.stem+'-'+revision+'.edges.sqlite')
            if not snapshot.is_file():raise ValueError('Missing snapshot')
            with sqlite3.connect(f'file:{sidecar.resolve()}?mode=ro',uri=True) as db:
                meta=dict(db.execute('SELECT key,value FROM metadata'))
                assert meta=={'format':'enc-edges-2','revision':revision,'snapshot':snapshot.stem},meta
                assert db.execute('PRAGMA quick_check').fetchall()==[('ok',)]
                assert db.execute('SELECT count(*) FROM links l LEFT JOIN edges e ON l.edge=e.id WHERE e.id IS NULL').fetchone()[0]==0
                assert db.execute('SELECT count(*) FROM links l LEFT JOIN features f ON l.class=f.class AND l.rcid=f.rcid WHERE f.rcid IS NULL').fetchone()[0]==0
                assert db.execute('SELECT count(*) FROM point_quality p LEFT JOIN features f ON p.class=f.class AND p.rcid=f.rcid WHERE f.rcid IS NULL OR f.prim!=1').fetchone()[0]==0
                for table in ['edges','features','links','point_quality']:totals[table]+=db.execute('SELECT count(*) FROM '+table).fetchone()[0]
                totals['masked_links']+=db.execute('SELECT count(*) FROM links WHERE mask=1').fetchone()[0]
                totals['quality_edges']+=db.execute('SELECT count(*) FROM edges WHERE quapos IS NOT NULL OR posacc IS NOT NULL').fetchone()[0]
                totals['unreliable_edges']+=db.execute('SELECT count(*) FROM edges WHERE quapos BETWEEN 2 AND 9').fetchone()[0]
                totals['unreliable_point_primitives']+=db.execute('SELECT count(*) FROM point_quality WHERE quapos BETWEEN 2 AND 9').fetchone()[0]
                totals['conditional_restrictions']+=db.execute("SELECT count(*) FROM features WHERE class='RESARE' AND priority=6").fetchone()[0]
                totals['contour_candidates']+=db.execute('SELECT count(*) FROM features WHERE contour=1').fetchone()[0]
                for table,histogram in [('edges',edge_quality),('point_quality',point_quality)]:
                    for quality,count in db.execute('SELECT quapos,count(*) FROM '+table+' GROUP BY quapos'):
                        key=str(quality);histogram[key]=histogram.get(key,0)+count
                for cls,count in db.execute('SELECT class,count(*) FROM features WHERE lookup_id=-1 GROUP BY class'):
                    unknown[cls]=unknown.get(cls,0)+count;totals['unmatched_lookups']+=count
            totals['bytes']+=sidecar.stat().st_size;totals['cells']+=1
        except Exception as error:errors.append({'cell':name,'error':str(error)})
    result={'recorded_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'revision':revision,'gdal':version,
            'seconds':round(time.monotonic()-started,3),'totals':totals,'edge_quapos':edge_quality,'point_quapos':point_quality,'unmatched_by_class':unknown,'errors':errors}
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    if errors:raise RuntimeError(f'{len(errors)} sidecars failed audit')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--catalogue',required=True,type=Path);p.add_argument('--cache',required=True,type=Path)
    p.add_argument('--ogr2ogr',default='/usr/bin/ogr2ogr',type=Path);p.add_argument('--out',required=True,type=Path)
    a=p.parse_args();audit(a.catalogue,a.cache,a.ogr2ogr,a.out)
