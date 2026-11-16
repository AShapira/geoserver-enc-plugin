#!/usr/bin/env python3
"""Install the pinned Linux x86_64 demo toolchain inside .runtime (no system changes)."""
import hashlib
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request
import zipfile
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'.runtime'


def download(url,path,sha):
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==sha: return
    with urllib.request.urlopen(url,timeout=180) as r: data=r.read()
    if hashlib.sha256(data).hexdigest()!=sha: raise RuntimeError('Checksum mismatch: '+url)
    path.write_bytes(data)


def main():
    if platform.system()!='Linux' or platform.machine()!='x86_64':
        raise SystemExit('This bootstrap is pinned to Linux x86_64. See README for other platforms.')
    RUNTIME.mkdir(exist_ok=True)
    download('https://micro.mamba.pm/api/micromamba/linux-64/2.10.0',RUNTIME/'micromamba.tar.bz2',
             '9a97976244929bbae28fb1fae504e74a3e7e6d1932870e3a03321f01b7fbd07b')
    if not (RUNTIME/'bin/micromamba').exists():
        with tarfile.open(RUNTIME/'micromamba.tar.bz2') as t: t.extract('bin/micromamba',RUNTIME,filter='data')
    if not (RUNTIME/'env/conda-meta/history').exists():
        subprocess.run([str(RUNTIME/'bin/micromamba'),'create','--no-rc','-y','-r',str(RUNTIME/'mamba'),
            '-p',str(RUNTIME/'env'),'-f',str(ROOT/'environment-linux-64.lock')],check=True)
    download('https://downloads.sourceforge.net/project/geoserver/GeoServer/3.0.2/geoserver-3.0.2-bin.zip',
        RUNTIME/'geoserver.zip','66520d9debefb7689b96c8b9b133430f0ebdb28e74ce58b2355d877b8e9a01bc')
    if not (RUNTIME/'geoserver/start.jar').exists():
        with zipfile.ZipFile(RUNTIME/'geoserver.zip') as z: z.extractall(RUNTIME/'geoserver')
    print('Ready. Run scripts/build.sh, then scripts/serve.sh.')


if __name__=='__main__': main()
