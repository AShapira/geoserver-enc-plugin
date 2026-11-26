"""Regression checks for provider history, worker recovery and offline catalog transfer."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from cache_key import snapshot_path
import catalog_manager as manager
from deployment import generation_id
from exchange import tree_digest
import prepared


class ManagerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base/'library'
        manager.initialize(self.root)
        self.folder = self.base/'cells'
        self.folder.mkdir()
        (self.folder/'CELL.000').write_bytes(b'base')
        (self.folder/'CELL.001').write_bytes(b'update')

    def job(self, provider, action='acquire'):
        with patch('catalog_manager.subprocess.Popen'):
            key = manager.start_job(self.root, provider['id'], action)
        manager.run_job(self.root, key, provider)
        return key

    def test_sources_snapshot_and_recovery(self):
        archive = self.base/'charts.zip'
        with zipfile.ZipFile(archive, 'w') as out:
            for path in self.folder.iterdir():
                out.write(path, path.name)
        for location in (str(self.folder), str(archive), 'https://authority.example/download?id=1'):
            provider_id = manager.save_provider(self.root, location, 'My charts')
            row = next(p for p in manager.state(self.root)['providers'] if p['id'] == provider_id)
            with patch('catalog_manager.download', lambda url, dest: dest.write_bytes(archive.read_bytes())):
                key = self.job(row)
            snapshot = self.root/'snapshots'/key
            self.assertEqual(tree_digest(snapshot), tree_digest(self.folder))
        with manager.job_lock(self.root), self.assertRaises(BlockingIOError):
            manager.start_job(self.root, provider_id, 'acquire')
        with patch('catalog_manager.subprocess.Popen'):
            interrupted = manager.start_job(self.root, provider_id, 'prepare', key)
        manager.save_provider(self.root, str(self.folder/'missing'), 'Renamed', provider_id)
        (self.folder/'CELL.001').write_bytes(b'changed')
        manager.initialize(self.root)
        state = manager.state(self.root)
        self.assertEqual(len(state['snapshots']), 3)
        self.assertEqual(len(state['providers']), 9)
        self.assertEqual(next(j for j in state['jobs'] if j['id'] == interrupted)['status'], 'interrupted')
        self.assertEqual((snapshot/'CELL.001').read_bytes(), b'update')
        self.assertEqual(next(p for p in state['providers'] if p['id'] == provider_id)['name'], 'Renamed')

    def test_bad_source_keeps_last_exchange_and_its_manifest(self):
        (self.folder/'exchange.json').write_text('{"format":"enc-exchange-1","expected_base_count":1}')
        key = manager.save_provider(self.root, str(self.folder))
        provider = next(p for p in manager.state(self.root)['providers'] if p['id'] == key)
        snapshot = self.root/'snapshots'/self.job(provider)
        self.assertEqual((snapshot/'exchange.json').read_bytes(), (self.folder/'exchange.json').read_bytes())
        (self.folder/'CELL.000').unlink()
        with self.assertRaisesRegex(ValueError, 'no S-57 base'):
            self.job(provider)
        self.assertEqual(len(manager.state(self.root)['snapshots']), 1)
        with patch('catalog_manager.download', lambda url, dest: dest.write_text('<html>chart website</html>')):
            with self.assertRaisesRegex(ValueError, 'direct ZIP'):
                manager.acquire(self.root, dict(kind='url', location='https://example.org'), self.base/'out')

    def test_failed_worker_can_retry_after_restart(self):
        location = self.base/'missing'
        provider = manager.save_provider(self.root, str(location))

        def acquire_and_wait():
            job_id = manager.start_job(self.root, provider, 'acquire')
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                job = next(j for j in manager.state(self.root)['jobs'] if j['id'] == job_id)
                if job['status'] != 'running':
                    return job
                time.sleep(.05)
            self.fail('Worker did not finish')

        failed = acquire_and_wait()
        self.assertEqual(failed['status'], 'failed')
        self.assertIn(str(location), failed['error'])
        self.folder.rename(location)
        manager.initialize(self.root)
        self.assertEqual(acquire_and_wait()['status'], 'complete')
        state = manager.state(self.root)
        self.assertEqual(len(state['snapshots']), 1)
        self.assertEqual(state['jobs'][-1]['status'], 'failed')

    def test_transfer_rejects_changed_content_runtime_and_cache_location(self):
        digest = tree_digest(self.folder)
        runtime = {'gdal': 'test GDAL'}
        generation = generation_id(digest, runtime)
        self.assertNotEqual(generation, generation_id(digest, {'gdal':'new GDAL'}))
        workspace = 'demo'
        directory = self.base/'source'/workspace/generation
        directory.mkdir(parents=True)
        self.folder.rename(directory/'exchange')
        (directory/'runtime.json').write_text(json.dumps(runtime))
        with closing(sqlite3.connect(directory/'catalogue.sqlite')) as db, db:
            db.execute('CREATE TABLE cells(path TEXT)')
            db.execute("INSERT INTO cells VALUES('exchange/CELL.000')")
            db.execute('CREATE TABLE metadata(key TEXT,value TEXT)')
            db.execute("INSERT INTO metadata VALUES('archive_sha256',?)", (digest,))
        (directory/'cache').mkdir()
        for name in prepared.REPORTS - {'catalogue.sqlite'}:
            (directory/name).write_text('report')
        canonical = prepared.ROOT/workspace/generation/'exchange/CELL.000'
        snapshot = snapshot_path(directory/'exchange/CELL.000', directory/'cache', None, runtime['gdal'],
                                 identity_path=canonical)
        snapshot.write_bytes(b'converted')
        snapshot.with_name(snapshot.stem+'-'+'a'*16+'.edges.sqlite').write_bytes(b'edges')
        package = self.base/'transfer.zip'
        prepared.export(directory, package, 'My charts')
        target = self.base/'install'
        prepared.install(package, workspace, runtime, target)
        installed = target/workspace/generation/'catalogue.sqlite'
        timestamp = installed.stat().st_mtime_ns
        prepared.install(package, workspace, runtime, target)
        with self.assertRaisesRegex(ValueError, 'Incompatible'):
            prepared.install(package, workspace, {'gdal':'other'}, target)
        for change in ('content', 'workspace'):
            damaged = self.base/(change+'.zip')
            with zipfile.ZipFile(package) as source, zipfile.ZipFile(damaged, 'w') as out:
                for name in source.namelist():
                    data = source.read(name)
                    if change == 'content' and name == 'edge-report.log':
                        data += b'changed'
                    if change == 'workspace' and name == 'prepared.json':
                        manifest = json.loads(data)
                        manifest['workspace'] = 'renamed'
                        data = json.dumps(manifest).encode()
                    out.writestr(name, data)
            with self.assertRaisesRegex(ValueError, 'Checksum mismatch|destination cache paths'):
                prepared.install(damaged, workspace if change == 'content' else 'renamed', runtime, target)
        self.assertFalse((target/'renamed'/generation).exists())
        self.assertEqual(installed.stat().st_mtime_ns, timestamp)
