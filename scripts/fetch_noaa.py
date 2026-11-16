#!/usr/bin/env python3
"""Download one NOAA ENC exchange set, retaining updates and provenance."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import re
import urllib.request
import zipfile


def fetch(cell, destination):
    if not re.fullmatch(r'US[1-6][A-Z0-9]{5}',cell):
        raise ValueError('Expected an eight-character NOAA cell ID, e.g. US5NY1BH')
    destination.mkdir(parents=True,exist_ok=True)
    url=f'https://charts.noaa.gov/ENCs/{cell}.zip'
    archive=destination/f'{cell}.zip'
    with urllib.request.urlopen(url,timeout=120) as response:
        content=response.read(100_000_001)
    if len(content)>100_000_000: raise ValueError('Unexpectedly large single-cell ZIP')
    archive.write_bytes(content)
    # Each download gets its own immutable extraction root: no stale .00n from older editions.
    digest=hashlib.sha256(content).hexdigest()
    root=destination/f'{cell}-{digest[:16]}'
    files=[]
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist())>500_000_000: raise ValueError('Uncompressed exchange set too large')
        for info in z.infolist():
            path=PurePosixPath(info.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in info.filename: raise ValueError('Unsafe ZIP path')
            target=root/str(path)
            if info.is_dir(): target.mkdir(parents=True,exist_ok=True); continue
            target.parent.mkdir(parents=True,exist_ok=True)
            data=z.read(info); target.write_bytes(data)
            files.append({'path':str(path),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    bases=list(root.rglob(f'{cell}.000'))
    if len(bases)!=1: raise ValueError('Expected exactly one matching base cell')
    manifest={'source':url,'retrieved_utc':datetime.now(timezone.utc).isoformat(),'archive_sha256':digest,'base':str(bases[0].resolve()),'files':files}
    (root/'provenance.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return bases[0]


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('cell',nargs='?',default='US5NY1BH')
    p.add_argument('--dest',type=Path,default=Path('data/noaa'))
    a=p.parse_args(); print(fetch(a.cell,a.dest).resolve())
