import hashlib
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from style_library import build, RESOURCE
from portrayal import OGC, select_styles


class StyleLibraryTest(unittest.TestCase):
    def test_packaged_library_matches_chart_free_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            build(Path(tmp))
            for name in ('style-library.zip','portrayal-schema.tsv'):
                self.assertEqual((RESOURCE/name).read_bytes(), (Path(tmp)/name).read_bytes())

    def test_each_style_uses_the_declared_schema_and_assets(self):
        fields = {}
        for line in (RESOURCE/'portrayal-schema.tsv').read_text().splitlines():
            cls,name,_ = line.split('\t')
            fields.setdefault(cls,set()).add(name)
        with zipfile.ZipFile(RESOURCE/'style-library.zip') as archive:
            manifest = json.loads(archive.read('enc-library-v1/manifest.json'))
            for path,digest in manifest['checksums'].items():
                self.assertEqual(hashlib.sha256(archive.read(path)).hexdigest(),digest)
            for palette,styles in manifest['palettes'].items():
                for cls,style in styles['layers'].items():
                    tree = ET.fromstring(archive.read(style+'.sld'))
                    required = {e.text for e in tree.iter('{'+OGC+'}PropertyName')}
                    self.assertFalse(required-fields[cls], (style,required-fields[cls]))
                    for e in tree.iter('{http://www.opengis.net/sld}OnlineResource'):
                        href = e.get('{http://www.w3.org/1999/xlink}href')
                        if not href.startswith('file:/enc-s52/'):
                            self.assertIn(href,manifest['checksums'])
                selection = select_styles(manifest,palette,{'DEPCNT':5,'unknown':1})
                self.assertEqual({'DEPCNT'},set(selection['layers']))
                self.assertEqual({'unknown':1},selection['unportrayed_classes'])
                self.assertEqual([5,8],[row['priority'] for row in selection['stack']])
