"""Export and install versioned offline catalog packages using the plugin's cache layout."""
from contextlib import closing
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess
import sys
import tempfile
import zipfile

from cache_key import snapshot_path
from deployment import ROOT, SCRIPT, generation_id, locked, stage
from exchange import tree_digest
from providers import sha

FORMAT = 'enc-prepared-1'
HEX = r'[0-9a-f]{64}'
WORKSPACE = r'[A-Za-z][A-Za-z0-9_]*'
REPORTS = {'.validated', 'catalogue.sqlite', 'catalogue-report.json', 'edge-report.log',
           'cache/warm-report.json'}
CACHE_FILE = rf'cache/{HEX}(?:\.gpkg|-[0-9a-f]{{16}}\.edges\.sqlite)'


def runtime():
    assets = Path('/opt/enc/s57')
    return {
        'plugin': sha(assets/'gs-s57.jar'),
        'gdal': subprocess.check_output([SCRIPT/'ogr_inland.py', '--version'], text=True).strip(),
        'dictionary': {p.name: sha(p) for p in sorted(assets.glob('*.csv'))},
        'recipe': sha(SCRIPT.parent/'src/main/resources/org/enc/geoserver/cache-recipe.txt'),
    }


def valid_member(name):
    path = PurePosixPath(name)
    return (str(path) == name and not path.is_absolute() and '..' not in path.parts
            and '\\' not in name and (name in REPORTS or name.startswith('exchange/')
                                      or re.fullmatch(CACHE_FILE, name)))


def transfer(source, dest=None):
    digest = hashlib.sha256()
    while block := source.read(1024 * 1024):
        digest.update(block)
        if dest is not None:
            dest.write(block)
    return digest.hexdigest()


def header(archive):
    data = json.loads(archive.read('prepared.json'))
    if (not isinstance(data, dict) or data.get('format') != FORMAT
            or not isinstance(data.get('title'), str) or not isinstance(data.get('runtime'), dict)
            or not re.fullmatch(WORKSPACE, data.get('workspace', ''))
            or not re.fullmatch(HEX, data.get('generation', ''))):
        raise ValueError('Invalid prepared catalog manifest')
    files = data['files']
    if not isinstance(files, dict) or not REPORTS.issubset(files):
        raise ValueError('Prepared catalog is missing required files')
    names = archive.namelist()
    if len(names) != len(files) + 1 or set(names) != set(files) | {'prepared.json'}:
        raise ValueError('ZIP entries differ from the prepared catalog manifest')
    if not all(valid_member(n) and re.fullmatch(HEX, h) for n, h in files.items()):
        raise ValueError('Invalid file or checksum in prepared catalog')
    return data


def verify(archive, data, directory=None):
    for name, checksum in data['files'].items():
        with archive.open(name) as stream:
            if directory is None:
                actual = transfer(stream)
            else:
                path = directory/name
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('xb') as output:
                    actual = transfer(stream, output)
        if checksum != actual:
            raise ValueError(f'Checksum mismatch for {name}')


def export(directory, destination, title):
    description = {'format': FORMAT, 'workspace': directory.parent.name, 'generation': directory.name,
                   'title': title, 'runtime': json.loads((directory/'runtime.json').read_text()),
                   'files': {}}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=f'.{destination.stem}-') as tmp:
        package = Path(tmp)/destination.name
        with zipfile.ZipFile(package, 'x', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            for path in sorted(directory.rglob('*')):
                name = path.relative_to(directory).as_posix()
                if path.is_file() and valid_member(name):
                    with path.open('rb') as source, archive.open(name, 'w', force_zip64=True) as out:
                        description['files'][name] = transfer(source, out)
            archive.writestr('prepared.json', json.dumps(description))
        validate_inventory(directory, description)
        print('Verifying exported package', flush=True)
        with zipfile.ZipFile(package) as archive:
            verify(archive, header(archive))
        checksum = sha(package)
        package.replace(destination)
    return checksum


def validate_inventory(directory, data):
    digest = tree_digest(directory/'exchange')
    if generation_id(digest, data['runtime']) != data['generation']:
        raise ValueError('Generation does not match the source exchange')
    with closing(sqlite3.connect((directory/'catalogue.sqlite').as_uri()+'?mode=ro', uri=True)) as db:
        paths = [row[0] for row in db.execute('SELECT path FROM cells')]
        indexed = db.execute("SELECT value FROM metadata WHERE key='archive_sha256'").fetchone()
    if not paths or indexed != (digest,):
        raise ValueError('Inventory does not match the source exchange')
    # Cache keys use the final container path even when validating a temporary import.
    canonical = ROOT/data['workspace']/data['generation']
    expected = set()
    for name in paths:
        if not name.startswith('exchange/') or name not in data['files']:
            raise ValueError(f'Missing indexed cell {name}')
        key = snapshot_path(directory/name, Path('cache'), None, data['runtime']['gdal'],
                            identity_path=canonical/name)
        expected.add(key.stem)
    snapshots = {Path(n).stem for n in data['files'] if n.startswith('cache/') and n.endswith('.gpkg')}
    edges = [Path(n).name.split('-')[0] for n in data['files']
             if n.startswith('cache/') and n.endswith('.edges.sqlite')]
    if expected != snapshots or set(edges) != expected or len(edges) != len(paths):
        raise ValueError('Converted cells or edge data do not match the destination cache paths')


def install(package, expected_workspace, current_runtime, root=ROOT):
    with zipfile.ZipFile(package) as archive:
        data = header(archive)
        if data['runtime'] != current_runtime:
            raise ValueError('Incompatible plugin, GDAL, dictionary or conversion recipe')
        if data['workspace'] != expected_workspace:
            raise ValueError('Package workspace differs from the requested workspace')
        parent = root/data['workspace']
        target = parent/data['generation']
        with locked(parent/'.stage.lock'), tempfile.TemporaryDirectory(dir=parent) as tmp:
            directory = Path(tmp)/'generation'
            verify(archive, data, directory)
            validate_inventory(directory, data)
            if target.exists():
                for name, checksum in data['files'].items():
                    if not (target/name).is_file() or sha(target/name) != checksum:
                        raise ValueError(f'Installed generation differs at {name}')
            else:
                directory.rename(target)
    print('ENC_GENERATION=' + data['generation'], flush=True)


if __name__ == '__main__':
    if sys.argv[1] == 'install':
        install(Path(sys.argv[2]), sys.argv[3], runtime())
    elif sys.argv[1] == 'stage':
        identity = runtime()
        directory = stage(Path('/input'), sys.argv[2], int(sys.argv[3]), sys.argv[4], identity)
        (directory/'runtime.json').write_text(json.dumps(identity))
    else:
        sys.exit('Expected stage or install')
