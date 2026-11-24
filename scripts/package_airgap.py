#!/usr/bin/env python3
"""Create the offline build and deployment kit from an explicit input allowlist."""
import argparse
import hashlib
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = ET.parse(ROOT / 'pom.xml').getroot().findtext('{http://maven.apache.org/POM/4.0.0}version')
if not VERSION or not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', VERSION):
    raise ValueError('Expected a valid project version in pom.xml')
DEFAULT_NAME = f'gs-s57-{VERSION}-airgap-build.zip'


def package(destination):
    dockerfile = (ROOT / 'airgap/Dockerfile').read_text()
    if set(re.findall(r'gs-s57-([0-9A-Za-z.-]+)\.jar', dockerfile)) != {VERSION}:
        raise ValueError('Air-gap Dockerfile plugin version does not match pom.xml')
    inputs = {
        'Dockerfile': ROOT / 'airgap/Dockerfile',
        '.dockerignore': ROOT / 'airgap/context.dockerignore',
        '.containerignore': ROOT / 'airgap/context.dockerignore',
        'README.md': ROOT / 'airgap/START-HERE.md',
        'LICENSE': ROOT / 'LICENSE',
        'NOTICE.md': ROOT / 'NOTICE.md',
    }
    operators = (
        'enc', 'viewer/enc.html', 'container/Dockerfile', 'airgap/README.md',
        'container/kartoza.Dockerfile', 'container/publish-kartoza.sh', 'container/demo.sh',
        'docs/airgap-deployment.md', 'docs/publishing-guide.md', 'docs/kartoza-2.28.0.md',
        'docs/noaa-catalogue-maintenance.md', 'docs/enc-validation.json', 'docs/shared-styles.md',
        'docs/portrayal.md', 'docs/portrayal-2026-11-17.md', 'docs/edge-metadata.md',
        'docs/portrayal-comparison.md', 'docs/catalogue-validation.md', 'docs/decisions.md',
    )
    scripts = (
        'providers', 'exchange', 'catalogue', 'deployment', 'inland_dictionary', 'ogr_inland',
        'warm_catalogue', 'cache_key', 'publish', 'portrayal', 'hpgl', 'check_sources',
        'catalogue_smoke', 'audit_edges', 'tune_cache',
    )
    for name in operators:
        inputs[name] = ROOT / name
    for script in scripts:
        name = f'scripts/{script}.py'
        inputs[name] = ROOT / name
    for directory in ('src/main', 'portrayal/upstream'):
        for path in sorted((ROOT / directory).rglob('*')):
            if path.is_file():
                if path.is_symlink():
                    raise ValueError(f'Unexpected symbolic link: {path}')
                if path.suffix in {'.class', '.jar', '.pyc'} or '__pycache__' in path.parts:
                    raise ValueError(f'Unexpected generated file: {path}')
                inputs[path.relative_to(ROOT).as_posix()] = path
    content = {name: path.read_bytes() for name, path in sorted(inputs.items())}
    checksums = ''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n'
                        for name, data in content.items())
    content['SHA256SUMS'] = checksums.encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(content.items()):
            # Stable metadata: the same inputs produce the same archive.
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            mode = 0o100755 if name in {'enc', 'container/demo.sh', 'scripts/ogr_inland.py'} else 0o100644
            info.external_attr = mode << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert all(archive.read(name) == data for name, data in content.items())
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_name(destination.name + '.sha256').write_text(
        digest + '  ' + destination.name + '\n')
    print(f'{destination}\n{len(content)} files; {destination.stat().st_size} bytes\nSHA-256 {digest}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / DEFAULT_NAME)
    package(parser.parse_args().output)
