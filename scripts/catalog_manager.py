"""Persistent provider library and background jobs for the local catalog manager."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from threading import Thread
from urllib.parse import unquote, urlsplit
import uuid
import zipfile

from deployment import run_generation
from exchange import manifest, tree_digest
from prepared import export
from providers import PROFILES, download, extract, prepare

PROJECT = Path(__file__).resolve().parents[1]


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@contextmanager
def database(root):
    with closing(sqlite3.connect(root/'manager.sqlite', timeout=10)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        with db:
            yield db


def initialize(root):
    for name in ('snapshots', 'logs', 'catalogues', 'exports'):
        (root/name).mkdir(parents=True, exist_ok=True)
    with database(root) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS providers(
                id TEXT PRIMARY KEY, name TEXT NOT NULL, location TEXT NOT NULL, kind TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS snapshots(
                id TEXT PRIMARY KEY, provider TEXT REFERENCES providers, created TEXT NOT NULL,
                location TEXT NOT NULL, digest TEXT NOT NULL, cells INTEGER, generation TEXT,
                package TEXT, checksum TEXT, bytes INTEGER);
            CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY, provider TEXT REFERENCES providers, action TEXT NOT NULL,
                snapshot TEXT, created TEXT NOT NULL, status TEXT NOT NULL, error TEXT);
        """)
        db.executemany('INSERT OR IGNORE INTO providers VALUES(?,?,?,?)',
                       [(key, profile[0], profile[3], 'builtin') for key, profile in PROFILES.items()])


def save_provider(root, location, name='', provider=None):
    location = location.strip()
    if not location:
        raise ValueError('Enter a download URL or local path')
    url = urlsplit(location)
    if url.scheme:
        if url.scheme not in ('http', 'https') or not url.hostname:
            raise ValueError('Use a direct HTTP(S) ZIP URL or a local path')
        kind = 'url'
        suggested = Path(unquote(url.path)).stem or url.hostname
    else:
        path = Path(location).expanduser().resolve()
        location = str(path)
        kind = 'local'
        suggested = path.stem if path.suffix.lower() == '.zip' else path.name
    name = name.strip() or suggested or 'Charts'
    with database(root) as db:
        db.execute('BEGIN IMMEDIATE')
        if provider:
            updated = db.execute("UPDATE providers SET name=?, location=?, kind=? WHERE id=? AND kind!='builtin'",
                                 (name, location, kind, provider))
            if not updated.rowcount:
                raise ValueError('Select a custom provider to edit')
        else:
            base = re.sub('[^a-z0-9]+', '_', name.lower()).strip('_')[:48]
            if not base or not base[0].isalpha():
                base = 'enc_' + base
            provider = base
            suffix = 2
            while db.execute('SELECT 1 FROM providers WHERE id=?', (provider,)).fetchone():
                provider = f'{base}_{suffix}'
                suffix += 1
            db.execute('INSERT INTO providers VALUES(?,?,?,?)', (provider, name, location, kind))
    return provider


def acquire(root, provider, dest):
    location = provider['location']
    if provider['kind'] == 'builtin':
        prepare(dest, provider['id'])
    else:
        local = Path(location)
        if provider['kind'] == 'local' and local.is_dir():
            if root.is_relative_to(local):
                raise ValueError('The exchange folder contains the manager data directory. Choose the chart folder itself.')
            print('Copying exchange folder', flush=True)
            original = tree_digest(local)
            shutil.copytree(local, dest, symlinks=True)
            if tree_digest(dest) != original:
                raise ValueError('Source changed during import')
        else:
            if provider['kind'] == 'url':
                local = dest.parent/'download.zip'
                print('Downloading chart archive', flush=True)
                download(location, local)
            elif not local.is_file():
                raise ValueError(f'Cannot read local chart source: {location}')
            if not zipfile.is_zipfile(local):
                raise ValueError('Source must contain a ZIP archive. For a website, use its direct ZIP download URL.')
            print('Extracting chart archive', flush=True)
            extract(local, dest)
    if not any(p.is_file() and not p.name.startswith('._') for p in dest.rglob('*.000')):
        raise ValueError('Exchange contains no S-57 base cells (.000)')
    manifest(dest)
    return tree_digest(dest)


def convert(root, provider, snapshot):
    # Standalone preparation shares the same assets and absolute cell paths as deployment.
    print('Checking offline conversion runtime', flush=True)
    assets = subprocess.check_output([PROJECT/'container/runtime.sh', '--offline'], text=True).strip()
    engine = os.environ.get('CONTAINER_ENGINE', 'podman')
    image = os.environ.get('ENC_OPERATOR_IMAGE', 'localhost/enc-operator:3.0.2')
    options = []
    if Path(engine).name == 'docker' and os.getuid() != 0:
        options = ['--user', f'{os.getuid()}:{os.getgid()}']
    return run_generation([engine, 'run', '--rm', '--pull=never', '--network', 'none', *options,
                    '-v', f'{assets}:/opt/enc/s57:ro',
                    '-v', f'{PROJECT}/scripts:/opt/enc/scripts:ro',
                    '-v', f'{root}/snapshots/{snapshot["id"]}:/input:ro',
                    '-v', f'{root}/catalogues:/opt/enc-cache/catalogues',
                    '--entrypoint', 'python3', image, '-u', '/opt/enc/scripts/prepared.py',
                    'stage', provider['id'], '4', snapshot['digest']])


def run_job(root, job_id, provider, worker_lock=None):
    with database(root) as db:
        job = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        snapshot = db.execute('SELECT * FROM snapshots WHERE id=?', (job['snapshot'],)).fetchone()
    action = job['action']
    if action == 'acquire':
        with tempfile.TemporaryDirectory(dir=root/'snapshots', prefix=f'.{job_id}-') as tmp:
            exchange = Path(tmp)/'exchange'
            digest = acquire(root, provider, exchange)
            exchange.rename(root/'snapshots'/job_id)
        statement = 'INSERT INTO snapshots(id,provider,created,location,digest) VALUES(?,?,?,?,?)'
        params = (job_id, provider['id'], now(), provider['location'], digest)
    else:
        parent = root/'catalogues'/provider['id']
        if action == 'prepare':
            generation = convert(root, provider, snapshot)
            directory = parent/generation
            cells = json.loads((directory/'catalogue-report.json').read_text())['indexed_cells']
            statement = 'UPDATE snapshots SET generation=?, cells=? WHERE id=?'
            if snapshot['generation'] != generation:
                statement = 'UPDATE snapshots SET generation=?, cells=?, package=NULL, checksum=NULL, bytes=NULL WHERE id=?'
            params = (generation, cells, snapshot['id'])
        else:
            package = root/'exports'/f'{provider["id"]}-{job_id}.zip'
            print('Writing transfer package', flush=True)
            checksum = export(parent/snapshot['generation'], package, provider['name'])
            statement = 'UPDATE snapshots SET package=?, checksum=?, bytes=? WHERE id=?'
            params = (str(package), checksum, package.stat().st_size, snapshot['id'])
    with database(root) as db:
        db.execute(statement, params)
        db.execute("UPDATE jobs SET status='complete' WHERE id=?", (job_id,))
        if worker_lock:
            worker_lock.close()  # Release before the terminal status becomes visible.


@contextmanager
def job_lock(root):
    with (root/'.job.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield lock


def recover(root, db):
    # Synchronize with a worker that released its file lock just before its final commit.
    db.execute('BEGIN IMMEDIATE')
    for job in db.execute("SELECT * FROM jobs WHERE status='running'"):
        if job['action'] == 'acquire':
            parent = root/'snapshots'
            prefix = job['id']
            orphan = parent/prefix
            if orphan.is_dir():
                shutil.rmtree(orphan)
        elif job['action'] == 'export':
            parent = root/'exports'
            prefix = f'{job["provider"]}-{job["id"]}'
            (parent/(prefix+'.zip')).unlink(missing_ok=True)
        else:
            continue
        for scratch in parent.glob(f'.{prefix}-*'):
            shutil.rmtree(scratch)
    db.execute("UPDATE jobs SET status='interrupted', error='Worker stopped. You can retry this action.' "
               "WHERE status='running'")


def start_job(root, provider_id, action, snapshot_id=None):
    if action not in ('acquire', 'prepare', 'export'):
        raise ValueError('Unknown catalog action')
    with job_lock(root) as lock:
        with database(root) as db:
            recover(root, db)
            provider = db.execute('SELECT * FROM providers WHERE id=?', (provider_id,)).fetchone()
            if not provider:
                raise ValueError('Unknown provider')
            if action != 'acquire':
                snapshot = db.execute('SELECT * FROM snapshots WHERE id=? AND provider=?',
                                      (snapshot_id, provider_id)).fetchone()
                if not snapshot:
                    raise ValueError('Choose a saved exchange for this provider')
                if action == 'export' and not snapshot['generation']:
                    raise ValueError('Prepare the catalog before exporting')
            job_id = uuid.uuid4().hex
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,'running',NULL)",
                       (job_id, provider_id, action, snapshot_id, now()))
        # The child inherits the lock and records its own result even if the UI restarts.
        with (root/'logs'/f'{job_id}.log').open('w') as log:
            worker = subprocess.Popen(
                [sys.executable, '-u', __file__, str(root), job_id, json.dumps(dict(provider)), str(lock.fileno())],
                stdout=log, stderr=subprocess.STDOUT, pass_fds=(lock.fileno(),), start_new_session=True)
            Thread(target=worker.wait, daemon=True).start()
    return job_id


def state(root):
    with database(root) as db:
        if db.execute("SELECT 1 FROM jobs WHERE status='running' LIMIT 1").fetchone():
            try:
                with job_lock(root):
                    recover(root, db)
                    db.commit()
            except BlockingIOError:
                pass
        providers = [dict(row) for row in db.execute('SELECT * FROM providers ORDER BY name COLLATE NOCASE')]
        for p in providers:
            if p['kind'] == 'builtin':
                p['attribution'] = PROFILES[p['id']][2]
        return {'dataDir': str(root), 'providers': providers,
                'snapshots': [dict(row) for row in db.execute('SELECT * FROM snapshots ORDER BY rowid DESC')],
                'jobs': [dict(row) for row in db.execute('SELECT * FROM jobs ORDER BY rowid DESC')]}


if __name__ == '__main__':
    data = Path(sys.argv[1])
    with os.fdopen(int(sys.argv[4]), 'a') as worker_lock:
        try:
            run_job(data, sys.argv[2], json.loads(sys.argv[3]), worker_lock)
        except Exception as error:
            print(error, flush=True)
            with database(data) as db:
                db.execute("UPDATE jobs SET status='failed', error=? WHERE id=?", (str(error), sys.argv[2]))
                worker_lock.close()
            sys.exit(1)
