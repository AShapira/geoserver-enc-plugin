"""Build the bundled ENC style library using only the pinned portrayal dictionaries."""
import argparse
import csv
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from portrayal import Compiler, PORTRAYAL_FIELDS, ROOT

VERSION = 1
PREFIX = f'enc_v{VERSION}_'
DIRECTORY = f'enc-library-v{VERSION}'
RESOURCE = ROOT / 'src/main/resources/org/enc/geoserver'
UPSTREAM = ROOT / 'portrayal/upstream'


def dictionaries():
    def rows(name):
        with (UPSTREAM / name).open(encoding='utf-8-sig') as stream:
            return [row for row in csv.DictReader(stream) if row['Code'].isdigit()]
    types = {a['Acronym']: {'E':'Integer','I':'Integer','F':'Real'}.get(a['Attributetype'],'String')
             for a in rows('s57attributes.csv')}
    result = {}
    for row in rows('s57objectclasses.csv'):
        cls = row['Acronym']
        if not cls or cls.startswith('M_'):
            continue
        fields = {name:types.get(name,'String') for column in ('Attribute_A','Attribute_B','Attribute_C')
                  for name in row[column].split(';') if name}
        fields.update(PRIM='Integer', OBJNAM='String', INFORM='String', NINFOM='String', NOBJNM='String')
        if cls == 'SOUNDG':
            fields['DEPTH'] = 'Real'
        if cls == 'TOPMAR':
            fields['_enc_floating'] = 'Integer'
        fields.update(PORTRAYAL_FIELDS)
        fields.update(_enc_shallow_depth='Real', _enc_safety_depth='Real', _enc_deep_depth='Real')
        result['i_'+cls if cls.islower() else cls] = fields
    return result


def build(destination):
    schemas = dictionaries()
    manifest = {'schema_version':VERSION, 'palettes':{}, 'checksums':{}, 'limitations':{}}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        used = set()
        for palette in ('day','dusk','night'):
            compiler = Compiler(UPSTREAM,root,palette)
            layers, stack = {}, []
            for cls,fields in sorted(schemas.items()):
                groups = compiler.compile(cls.removeprefix('i_'),fields)
                if not groups:
                    continue
                used.add(cls)
                name = PREFIX+palette+'_'+cls.replace('$','cart_')
                combined = []
                for priority,rules in sorted(groups.items()):
                    style = f'{name}_{priority}'
                    compiler.write_style(style,rules)
                    stack.append({'class':cls,'priority':priority,'style':style})
                    combined.extend(rules)
                compiler.write_style(name,combined)
                layers[cls] = name
            manifest['palettes'][palette] = {'layers':layers,'stack':sorted(stack,key=lambda e:(e['priority'],e['class']))}
            manifest['limitations'][palette] = sorted(compiler.issues)
        schema = ''.join(f'{cls}\t{name}\t{kind}\n' for cls in sorted(used)
                         for name,kind in sorted(schemas[cls].items()))
        destination.mkdir(parents=True,exist_ok=True)
        (destination/'portrayal-schema.tsv').write_text(schema)
        path = destination/'style-library.zip'
        with zipfile.ZipFile(path.with_suffix('.tmp'),'w') as archive:
            def put(name,data):
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info,data)
            for p in sorted(root.rglob('*')):
                if p.is_dir():
                    continue
                name = p.relative_to(root).as_posix()
                data = p.read_bytes()
                if name.startswith('symbols/'):
                    name = DIRECTORY+'/'+name
                else:
                    data = data.replace(b'xlink:href="symbols/',f'xlink:href="{DIRECTORY}/symbols/'.encode())
                manifest['checksums'][name] = hashlib.sha256(data).hexdigest()
                put(name,data)
            manifest['revision'] = hashlib.sha256(schema.encode()+json.dumps(manifest,sort_keys=True).encode()).hexdigest()
            put(DIRECTORY+'/manifest.json',json.dumps(manifest,sort_keys=True,separators=(',',':')).encode())
        path.with_suffix('.tmp').replace(path)
        print(f'{len(used)} classes, {len(manifest["checksums"])} resources, {manifest["revision"]}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=RESOURCE)
    build(parser.parse_args().out)
