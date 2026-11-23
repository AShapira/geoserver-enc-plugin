"""Migrate an offline GeoServer file catalogue copy after its first library startup."""
import argparse
import hashlib
from functools import lru_cache
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def replace_file(path, data):
    tmp = path.with_name(path.name+'.enc-tmp')
    tmp.write_bytes(data)
    tmp.chmod(path.stat().st_mode)
    tmp.replace(path)


def migrate(root, trusted, apply, cleanup):
    """Trusted directories must be independently verified legacy installations."""
    manifest = json.loads((root/'styles/enc-library-v1/manifest.json').read_bytes())
    targets = {}
    for name in manifest['checksums']:
        if name.endswith('.sld'):
            style = ET.parse(root/'styles'/(name[:-4]+'.xml')).getroot()
            if style.findtext('name') != name[:-4]:
                raise ValueError('Unexpected installed style: '+name)
            targets[name[:-4]] = style.findtext('id')
    @lru_cache(maxsize=None)
    def verified(path):
        if not path.is_file() or path.is_symlink():
            return False
        data = path.read_bytes()
        if path.parent == root/'styles/enc-symbols' and hashlib.sha256(data).hexdigest()==path.stem:
            return True
        return any((d/path.relative_to(root)).is_file() and
                   (d/path.relative_to(root)).read_bytes()==data for d in trusted)

    def verified_graphics(sld):
        for res in ET.parse(sld).iter('{http://www.opengis.net/sld}OnlineResource'):
            href = res.get('{http://www.w3.org/1999/xlink}href','')
            if href.startswith('file:/enc-s52/'):
                continue
            if not re.fullmatch(r'(symbols|enc-symbols)/[A-Za-z0-9_$.-]+\.png',href):
                return False
            if not verified(sld.parent/href):
                return False
        return True

    paths = [*root.glob('styles/enc_*.xml'), *root.glob('workspaces/*/styles/enc_*.xml')]
    mapping, files, retained = {}, {}, []
    for path in paths:
        style = ET.parse(path).getroot()
        name = style.findtext('name','')
        match = re.fullmatch(r'enc_(day|dusk|night)_(.+?)(?:_[a-f0-9]{20})?',name)
        if not match:
            continue
        new = 'enc_v1_'+match[1]+'_'+match[2].replace('$','cart_')
        sld = path.with_suffix('.sld')
        if (new not in targets or style.findtext('filename') != sld.name or not sld.is_file()
                or not verified(sld) or not verified_graphics(sld)):
            retained.append(str(path.relative_to(root)))
            continue
        identifier = style.findtext('id')
        mapping[identifier] = targets[new]
        files[identifier] = (path,sld)
    # Limit reassignment to existing S-57 chart stores and their chart groups.
    changed = {}
    for store in root.glob('workspaces/*/chart/datastore.xml'):
        if ET.parse(store).findtext(".//entry[@key='dbtype']") != 's57':
            continue
        ws = store.parent.parent
        resources = [*store.parent.glob('*/layer.xml'),*ws.glob('layergroups/chart_*.xml')]
        for path in resources:
            original = path.read_bytes()
            refs = set(re.findall(rb'<id>([^<]+)</id>',original))
            updated = original
            for ref in refs:
                if ref.decode() in mapping:
                    updated = updated.replace(b'<id>'+ref+b'</id>',b'<id>'+mapping[ref.decode()].encode()+b'</id>')
            if original != updated:
                changed[path] = updated
    if cleanup and changed:
        raise ValueError('Apply reassignment and verify rendered maps before cleanup')
    if apply:
        for path,data in changed.items():
            replace_file(path,data)
    registry = root/'www/enc-sources.json'
    if apply and registry.is_file():
        records = json.loads(registry.read_bytes())
        registered_ids = set(targets.values())
        for ws, record in records.items():
            directory = root/'workspaces'/ws
            groups = list(directory.glob('layergroups/chart_*.xml'))
            store = directory/'chart/datastore.xml'
            if not store.is_file() or not groups:
                continue
            params = {e.get('key'):e.text for e in ET.parse(store).findall('.//entry')}
            if params.get('dbtype') != 's57':
                continue
            assignments = [{e.text for e in ET.parse(g).findall('styles/style/id')} for g in groups]
            if all(ids and ids <= registered_ids for ids in assignments):
                safety = float(params.get('safetyDepth',5))
                record.update(library_revision=manifest['revision'], depths=[
                    float(params.get('shallowDepth',min(2,safety))),safety,float(params.get('deepDepth',max(10,safety)))])
                record.pop('portrayal_version',None)
        replace_file(registry,(json.dumps(records,indent=2,ensure_ascii=False)+'\n').encode())
    removed,graphics = [],[]
    if cleanup:
        # Require a separate pass after renders have been checked.
        refs = set()
        candidates = {p for p,_ in files.values()}
        for path in root.rglob('*.xml'):
            if path not in candidates:
                refs.update(re.findall(rb'<id>([^<]+)</id>',path.read_bytes()))
        for identifier,pair in files.items():
            if identifier.encode() not in refs:
                for path in pair:
                    removed.append(str(path.relative_to(root)))
                    if apply: path.unlink()
        # Resolve relative graphics in the style's own directory. A dynamic path or
        # an unfamiliar style format makes graphics cleanup ambiguous.
        removed_paths = {root/name for name in removed}
        styles = [p for folder in [root/'styles',*root.glob('workspaces/*/styles')]
                  for p in folder.iterdir() if p.is_file() and p.suffix!='.xml' and p not in removed_paths]
        keep = set()
        uncertain = any(p.suffix!='.sld' for p in styles)
        for path in styles:
            if path.suffix!='.sld': continue
            for resource in ET.parse(path).iter('{http://www.opengis.net/sld}OnlineResource'):
                href = resource.get('{http://www.w3.org/1999/xlink}href','')
                if href.startswith('file:/enc-s52/'): continue
                if '$' in href or ':' in href:
                    uncertain = True
                else:
                    keep.add((path.parent/href).resolve())
        if not uncertain:
            for folder in [root/'styles/enc-symbols',*root.glob('workspaces/*/styles/symbols')]:
                for png in folder.glob('*.png'):
                    if verified(png) and png.resolve() not in keep:
                        graphics.append(str(png.relative_to(root)))
                        if apply: png.unlink()
    return {'mapped':len(mapping),'updated':len(changed),'retained_unverified':retained,
            'removed':removed,'removed_graphics':graphics}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('offline_data_dir',type=Path)
    parser.add_argument('--trusted-legacy-data-dir',action='append',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--cleanup',action='store_true')
    args=parser.parse_args()
    if any(p.resolve()==args.offline_data_dir.resolve() for p in args.trusted_legacy_data_dir):
        parser.error('A separate known-good legacy installation is required')
    print(json.dumps(migrate(args.offline_data_dir,args.trusted_legacy_data_dir,args.apply,args.cleanup),indent=2))
