#!/usr/bin/env python3
"""Collect the verified plugin releases, build sources and operator tools."""
import argparse
import hashlib
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = ET.parse(ROOT/'pom.xml').getroot().findtext('{*}version')


def package(destination):
    files = {'README.md': ROOT/'airgap/START-HERE.md'}
    names = ['enc', 'pom.xml', 'LICENSE', 'NOTICE.md', '.containerignore', '.dockerignore',
             'docs/airgap-deployment.md', 'docs/publishing-guide.md', 'docs/kartoza-2.28.0.md',
             'docs/noaa-catalogue-maintenance.md', 'docs/shared-styles.md', 'docs/portrayal.md',
             'docs/edge-metadata.md', 'docs/catalogue-validation.md', 'docs/decisions.md',
             'docs/plugin-install-validation.json', 'cloud/README.md', 'cloud/build.sh', 'cloud/Dockerfile',
             'cloud/compose.yml', 'cloud/config.Dockerfile', 'cloud/check.py', 'cloud/integrate.py', 'cloud/s57-pom.xml',
             'airgap/README.md', 'airgap/START-HERE.md', 'container/build-plugins.sh', 'container/builder.Dockerfile',
             'container/operator.sh', 'container/operator.Dockerfile', 'container/demo.sh']
    for version in ('2.28.0', '3.0.2'):
        archive = ROOT/'dist'/f'geoserver-{version}-s57-plugin.zip'
        checksum = archive.with_suffix('.zip.sha256')
        if checksum.read_text().strip() != f'{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}':
            raise ValueError(f'SHA-256 mismatch for {archive}')
        names.extend(str(p.relative_to(ROOT)) for p in (archive, checksum))
    for directory, pattern in [('src','*'),('portrayal/upstream','*'),('scripts','*.py'),('tests','*.py')]:
        for path in (ROOT/directory).rglob(pattern):
            if path.is_file() and '__pycache__' not in path.parts:
                if path.is_symlink() or path.suffix in ('.class', '.pyc'):
                    raise ValueError(f'Unexpected package input {path}')
                names.append(str(path.relative_to(ROOT)))
    files.update((name, ROOT/name) for name in names)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        output = Path(tmp)/destination.name
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            sums = []
            for name, path in sorted(files.items()):
                data = path.read_bytes()
                info = zipfile.ZipInfo(name, (2026,1,1,0,0,0))
                info.external_attr = (0o100755 if path.stat().st_mode & 0o111 else 0o100644) << 16
                archive.writestr(info, data, zipfile.ZIP_DEFLATED)
                sums.append(f'{hashlib.sha256(data).hexdigest()}  {name}\n')
            archive.writestr(zipfile.ZipInfo('SHA256SUMS', (2026,1,1,0,0,0)), ''.join(sums))
        output.replace(destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.zip.sha256').write_text(f'{digest}  {destination.name}\n')
    print(destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'dist'/f'gs-s57-{VERSION}-airgap-build.zip')
    package(parser.parse_args().output)
