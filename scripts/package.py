#!/usr/bin/env python3
"""Package the binary, reproducible source, portrayal resources, and notices."""
import hashlib
from pathlib import Path
import zipfile
ROOT=Path(__file__).resolve().parents[1]
jar=ROOT/'target/gs-s57-0.1.0.jar'
if not jar.is_file(): raise SystemExit('Run scripts/build.sh first')
dest=ROOT/'dist';dest.mkdir(exist_ok=True)
archive=dest/'gs-s57-0.1.0-geoserver-3.0.2.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    z.write(jar,'lib/'+jar.name)
    for name in ['README.md','LICENSE','NOTICE.md','pom.xml','environment-linux-64.lock','.containerignore','.dockerignore']:
        z.write(ROOT/name,name)
    for directory in ['src','scripts','tests','docs','portrayal/upstream','container','viewer','evidence/portrayal','evidence/performance','evidence/optimization-2026-11-16','evidence/portrayal-2026-11-17']:
        for p in sorted((ROOT/directory).rglob('*')):
            # Packaging receipts contain this archive's hash and must stay external.
            if p.is_file() and '__pycache__' not in p.parts and p.name not in {'package.log','package-verification.json'}:
                z.write(p,str(p.relative_to(ROOT)))
checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix('.zip.sha256').write_text(checksum+'  '+archive.name+'\n')
print(archive);print(checksum)
