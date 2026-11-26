"""Container-side staging and publication for the enc command."""
import fcntl
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
import shutil
import sys
import tempfile
from contextlib import contextmanager
from exchange import inventory, manifest, tree_digest
from warm_catalogue import warm

ROOT = Path('/opt/enc-cache/catalogues')
SCRIPT = Path(__file__).resolve().parent


@contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def generation_id(digest, runtime=None):
    identity = 'enc-index-2:' + digest
    if runtime is not None:
        identity += ':' + json.dumps(runtime, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(identity.encode()).hexdigest()


def run_generation(command):
    generation = None
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as child:
        for line in child.stdout:
            print(line, end='', flush=True)
            match = re.fullmatch(r'ENC_GENERATION=([0-9a-f]{64})', line.strip())
            if match:
                generation = match[1]
        if child.wait() or generation is None:
            raise RuntimeError('Catalog staging failed. See the preceding operation log.')
    return generation


def stage(source, workspace, workers, expected_digest=None, runtime=None):
    os.environ['S57_CSV']='/opt/enc/s57'
    parent = ROOT / workspace
    with locked(parent / '.stage.lock'):
        digest = tree_digest(source)
        if expected_digest is not None and digest != expected_digest:
            raise ValueError("Saved exchange checksum has changed")
        generation = generation_id(digest, runtime)
        target = parent / generation
        if not target.exists():
            with tempfile.TemporaryDirectory(dir=parent) as tmp:
                out = Path(tmp) / 'generation'
                copy = out / 'exchange'
                shutil.copytree(source, copy, symlinks=True)
                if tree_digest(copy) != digest:
                    raise ValueError('Exchange changed while staging')
                try:
                    print('Indexing exchange cells', flush=True)
                    inventory(copy, out, workers, digest)
                except Exception:
                    report = out/'catalogue-report.json'
                    if report.is_file():
                        shutil.copyfile(report, parent/('failed-'+generation+'.json'))
                    raise
                out.rename(target)
        converter = SCRIPT/'ogr_inland.py'
        cache = target/'cache'
        jar = Path('/opt/enc/s57/gs-s57.jar')
        stamp = target/'.validated'
        recipe = hashlib.sha256(jar.read_bytes()+subprocess.check_output([str(converter),'--version'])).hexdigest()
        if not stamp.exists() or stamp.read_text() != recipe:
            index = target/'catalogue.sqlite'
            print('Converting cells to GeoPackages', flush=True)
            warm(index,cache,converter,workers)
            with (target/'edge-report.log').open('w') as report:
                print('Building edge data', flush=True)
                with subprocess.Popen(['java','-Xmx1g','-cp',str(jar) + ':/usr/local/tomcat/webapps/geoserver/WEB-INF/lib/*',
                    'org.enc.geoserver.EdgeCache',str(index),str(cache),str(converter),str(workers)],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as child:
                    for line in child.stdout:
                        print(line, end='', flush=True)
                        report.write(line)
                    status = child.wait()
            if status:
                raise RuntimeError('Edge validation failed: '+str(target/'edge-report.log'))
            stamp.write_text(recipe)
        print('ENC_GENERATION=' + generation, flush=True)
        return target


def publish(workspace, generation, title, view=None):
    from publish import publish_catalogue
    parent = ROOT / workspace
    directory = parent / generation
    with locked(ROOT / '.publish.lock'):
        profile = manifest(directory/'exchange')
        if view is not None:
            profile['view'] = view
        publish_catalogue(directory, workspace, title, profile)


if __name__ == '__main__':
    if sys.argv[1]=='stage':
        stage(Path(sys.argv[2]),sys.argv[3],int(sys.argv[4]))
    elif sys.argv[1]=='publish':
        publish(sys.argv[2],sys.argv[3],sys.argv[4] if len(sys.argv)>4 else None,
                json.loads(sys.argv[5]) if len(sys.argv)>5 else None)
    elif sys.argv[1]=='existing-noaa':
        from providers import PROFILES
        from publish import publish_catalogue
        title,kind,credit,url,view = PROFILES['noaa']
        with locked(ROOT/'.publish.lock'):
            registry = Path(os.environ.get('GEOSERVER_DATA_DIR','/opt/geoserver_data'))/'www/enc-sources.json'
            if '--if-missing' in sys.argv and registry.exists() and 'noaa' in json.loads(registry.read_text()):
                sys.exit(0)
            publish_catalogue(ROOT/'noaa'/'deployed','noaa',title,
                dict(product=kind,attribution=credit,source=url,view=view),
                Path('/opt/enc-data/catalogue.sqlite'),ROOT.parent,Path('/usr/bin/ogr2ogr'))
    else:
        raise ValueError('Unknown operation')
