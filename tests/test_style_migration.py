import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from migrate_style_library import migrate


class StyleMigrationTest(unittest.TestCase):
    def test_edited_graphics_and_references_in_other_workspaces_survive_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'catalog'; trusted=Path(tmp)/'original'
            folder=root/'workspaces/chart/styles'
            (folder/'symbols').mkdir(parents=True)
            (root/'styles/enc-library-v1').mkdir(parents=True)
            store=folder.parent/'chart'
            (store/'LIGHTS').mkdir(parents=True)
            (store/'datastore.xml').write_text('<dataStore><entry key="dbtype">s57</entry></dataStore>')
            layer=store/'LIGHTS/layer.xml'
            layer.write_text('<layer><defaultStyle><id>old</id></defaultStyle></layer>')
            (folder/'enc_day_LIGHTS.xml').write_text('<style><name>enc_day_LIGHTS</name><id>old</id><filename>enc_day_LIGHTS.sld</filename></style>')
            sld=folder/'enc_day_LIGHTS.sld'
            sld.write_text('<s:StyledLayerDescriptor xmlns:s="http://www.opengis.net/sld" xmlns:x="http://www.w3.org/1999/xlink"><s:OnlineResource x:href="symbols/light.png"/></s:StyledLayerDescriptor>')
            png=folder/'symbols/light.png';png.write_bytes(b'original')
            (root/'styles/enc_v1_day_LIGHTS.xml').write_text('<style><id>new</id><name>enc_v1_day_LIGHTS</name></style>')
            manifest={'checksums':{'enc_v1_day_LIGHTS.sld':hashlib.sha256(b'sld').hexdigest()}}
            (root/'styles/enc-library-v1/manifest.json').write_text(json.dumps(manifest))
            shutil.copytree(root,trusted)
            png.write_bytes(b'edited')
            self.assertEqual(0,migrate(root,[trusted],True,False)['mapped'])
            self.assertIn('<id>old</id>',layer.read_text())
            png.write_bytes(b'original')
            self.assertEqual(1,migrate(root,[trusted],True,False)['updated'])
            self.assertIn('<id>new</id>',layer.read_text())
            other=root/'layergroups/other.xml';other.parent.mkdir()
            other.write_text('<layerGroup><styles><style><id>old</id></style></styles></layerGroup>')
            self.assertFalse(migrate(root,[trusted],True,True)['removed'])
            self.assertTrue(png.is_file())
            other.unlink()
            self.assertEqual(2,len(migrate(root,[trusted],True,True)['removed']))
            self.assertFalse(png.exists())
            self.assertFalse(migrate(root,[trusted],True,True)['removed'])
