"""Cache identity shared with GdalCache.java through its recipe resource."""
import hashlib
from pathlib import Path
import subprocess


def snapshot_path(cell, cache, ogr2ogr, version=None):
    cell=cell.resolve()
    recipe=(Path(__file__).resolve().parents[1]/'src/main/resources/org/enc/geoserver/cache-recipe.txt').read_text().strip()
    if version is None: version=subprocess.run([str(ogr2ogr.resolve()),'--version'],capture_output=True,text=True,check=True,timeout=30).stdout.strip()
    digest=hashlib.sha256((recipe+'\n'+version+'\n'+str(cell)).encode())
    for p in sorted(cell.parent.glob(cell.stem+'.[0-9][0-9][0-9]')):
        if p.is_file():
            digest.update(p.name.encode())
            with p.open('rb') as stream:
                while data:=stream.read(65536): digest.update(data)
    return cache/(digest.hexdigest()+'.gpkg')
