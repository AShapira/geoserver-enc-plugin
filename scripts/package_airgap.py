#!/usr/bin/env python3
"""Create the source-only offline image-build kit from an explicit input allowlist."""
import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NAME = 'gs-s57-0.1.0-airgap-build-geoserver-2.28.0.zip'


def package(destination):
    inputs = {
        'Dockerfile': ROOT / 'airgap/Dockerfile',
        '.dockerignore': ROOT / 'airgap/context.dockerignore',
        '.containerignore': ROOT / 'airgap/context.dockerignore',
        'README.md': ROOT / 'airgap/README.md',
        'LICENSE': ROOT / 'LICENSE',
        'NOTICE.md': ROOT / 'NOTICE.md',
    }
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
            info.external_attr = 0o100644 << 16
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
