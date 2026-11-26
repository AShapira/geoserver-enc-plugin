#!/usr/bin/env python3
"""Build each standalone plugin from its own source tree and Maven profile."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {'2.28.0': ['-Pgeoserver-2.28'], '3.0.2': []}


def build(version, destination, offline, repository):
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp)
        shutil.copy2(ROOT / 'pom.xml', project)
        shutil.copytree(ROOT / 'src', project / 'src')
        shutil.copytree(ROOT / 'portrayal/upstream', project / 'portrayal/upstream')
        args = ['mvn', '-B', '-ntp', *TARGETS[version]]
        if offline:
            args.append('-o')
        if repository:
            args.append('-Dmaven.repo.local=' + str(repository.resolve()))
        subprocess.run([*args, 'package'], cwd=project, check=True)
        jar, = (project / 'target').glob('gs-s57-*.jar')
        with zipfile.ZipFile(jar) as artifact:
            for resource in ('index.html', 'viewer.js', 'viewer.css'):
                if not artifact.getinfo('enc/viewer/'+resource).file_size:
                    raise ValueError('Empty viewer resource: '+resource)
            manifest = artifact.read('META-INF/MANIFEST.MF').decode().splitlines()
            if f'GeoServer-Version: {version}' not in manifest:
                raise ValueError(f'Built JAR does not target GeoServer {version}')
        archive = destination / f'geoserver-{version}-s57-plugin.zip'
        with tempfile.TemporaryDirectory(dir=destination) as staging:
            staged = Path(staging) / archive.name
            with zipfile.ZipFile(staged, 'w', zipfile.ZIP_DEFLATED) as z:
                for path in (jar, ROOT/'LICENSE', ROOT/'NOTICE.md'):
                    info = zipfile.ZipInfo(path.name, (2026, 1, 1, 0, 0, 0))
                    info.external_attr = 0o100644 << 16
                    z.writestr(info, path.read_bytes(), zipfile.ZIP_DEFLATED)
            os.replace(staged, archive)
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        archive.with_suffix('.zip.sha256').write_text(f'{checksum}  {archive.name}\n')
        print(archive, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--repository', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT/'dist')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for version in TARGETS:
        build(version, args.output, args.offline, args.repository)
