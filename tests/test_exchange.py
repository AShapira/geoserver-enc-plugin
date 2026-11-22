from pathlib import Path
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from exchange import inventory, tree_digest
from providers import extract, prepare


class ExchangeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_portable_directory_and_update_fingerprint(self):
        archive = self.root / 'source.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('ENC_ROOT/CELL.000', b'base')
            z.writestr('ENC_ROOT/CELL.001', b'update')
        out = self.root / 'first'
        prepare(out, archives=[archive])
        self.assertEqual(json.loads((out/'exchange.json').read_text())['packages'][0]['name'], 'source')
        fingerprint = tree_digest(out)
        moved = out.rename(self.root/'moved')
        self.assertEqual(fingerprint, tree_digest(moved))
        next(moved.rglob('*.001')).write_bytes(b'different update')
        self.assertNotEqual(fingerprint, tree_digest(moved))

    def test_zip_preserves_extraction_boundary(self):
        archive = self.root/'invalid.zip'
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('../outside',b'bad path')
        with self.assertRaisesRegex(ValueError,'Unsafe archive entry'):
            extract(archive,self.root/'input')
        self.assertFalse((self.root/'outside').exists())

    def test_duplicate_update_chains_and_orphan_update(self):
        src = self.root/'exchange'
        first = src/'a'
        first.mkdir(parents=True)
        (first/'CELL.000').write_bytes(b'base')
        (first/'CELL.001').write_bytes(b'update')
        other = src/'b'
        shutil.copytree(first,other)
        with patch('catalogue.write_index') as write:
            inventory(src,self.root,1,'digest')
            self.assertEqual(len(write.call_args.args[0]),1)
            self.assertEqual(write.call_args.args[-1]['identical_duplicates'],['CELL'])
        (other/'CELL.001').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'Conflicting copies'):
            inventory(src,self.root,1,'digest')
        (other/'ORPHAN.002').write_bytes(b'update')
        with self.assertRaisesRegex(ValueError,'without adjacent'):
            inventory(src,self.root,1,'digest')
