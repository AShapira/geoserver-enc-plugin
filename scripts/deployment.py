"""Container-side staging and publication for the enc command."""
import fcntl
import hashlib
import json
import os
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


def stage(source, workspace, workers):
    os.environ['S57_CSV']='/opt/enc/s57'
    parent = ROOT / workspace
    with locked(parent / '.stage.lock'):
        digest = tree_digest(source)
        generation = hashlib.sha256(('enc-index-2:' + digest).encode()).hexdigest()
        target = parent / generation
        if not target.exists():
            with tempfile.TemporaryDirectory(dir=parent) as tmp:
                out = Path(tmp) / 'generation'
                copy = out / 'exchange'
                shutil.copytree(source, copy, symlinks=True)
                if tree_digest(copy) != digest:
                    raise ValueError('Exchange changed while staging')
                try:
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
            warm(index,cache,converter,workers)
            with (target/'edge-report.log').open('w') as report:
                result = subprocess.run(['java','-Xmx1g','-cp',str(jar) + ':/usr/local/tomcat/webapps/geoserver/WEB-INF/lib/*',
                    'org.enc.geoserver.EdgeCache',str(index),str(cache),str(converter),str(workers)],
                    stdout=report,stderr=subprocess.STDOUT)
            if result.returncode:
                raise RuntimeError('Edge validation failed: '+str(target/'edge-report.log'))
            stamp.write_text(recipe)
        print('ENC_GENERATION=' + generation, flush=True)


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
