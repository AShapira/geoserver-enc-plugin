"""Fingerprint and inventory a portable exchange directory without any network access."""
from collections import defaultdict
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from providers import sha


def tree_digest(root):
    digest = hashlib.sha256()
    for p in sorted(root.rglob('*')):
        if p.is_symlink() or not (p.is_dir() or p.is_file()):
            raise ValueError(f'Expected an ordinary file or directory: {p}')
        if p.is_file():
            digest.update(p.relative_to(root).as_posix().encode() + b'\0' + bytes.fromhex(sha(p)))
    return digest.hexdigest()


def manifest(root):
    path = root / 'exchange.json'
    if not path.is_file():
        return {}
    data = json.loads(path.read_text())
    if data.get('format') != 'enc-exchange-1':
        raise ValueError('Unsupported exchange manifest format')
    return data


def inventory(root, out, workers, digest):
    from catalogue import write_index
    data = manifest(root)
    groups = defaultdict(list)
    for p in sorted(root.rglob('*')):
        if not p.is_file() or not re.fullmatch(r'\.\d{3}', p.suffix):
            continue
        if p.name.startswith('._') or p.name.upper() == 'CATALOG.031':
            continue
        if p.suffix == '.000':
            groups[p.stem].append(p)
        elif not p.with_suffix('.000').is_file():
            raise ValueError(f'Update without adjacent base cell: {p}')
    count = sum(map(len, groups.values()))
    if not count or count != data.get('expected_base_count', count):
        raise ValueError(f'Unexpected base count {count}, expected {data.get("expected_base_count")}')
    expected = data.get('expected_cells')
    if expected is not None and set(expected) != set(groups):
        raise ValueError(f'Inventory differs: {sorted(set(expected) ^ set(groups))}')
    records = {}
    cancelled = 0
    if data.get('noaa_catalogue'):
        if data['noaa_catalogue'] != 'ENCProdCat.xml':
            raise ValueError('Unexpected NOAA inventory path')
        for c in ET.parse(root / 'ENCProdCat.xml').getroot().findall('cell'):
            if c.findtext('status') == 'Active':
                records[c.findtext('name')] = (c.findtext('lname'),int(c.findtext('edtn')),int(c.findtext('updn')))
            else:
                cancelled += 1
        if not records or set(records) - set(groups):
            raise ValueError('NOAA active inventory is incomplete')
    tasks = []
    duplicates = []
    for name in sorted(records or groups):
        paths = groups[name]
        if len(paths) > 1:
            chains = [{p.name:sha(p) for p in path.parent.glob(name+'.[0-9][0-9][0-9]')} for path in paths]
            if any(chain != chains[0] for chain in chains[1:]):
                raise ValueError(f'Conflicting copies of {name}: {paths}')
            duplicates.append(name)
        base = paths[0]
        tasks.append((name,str(base),str(base.relative_to(out)),*records.get(name,(name,None,None))))
    return write_index(tasks, out, workers, {'archive_sha256':digest,'base_files':count,
        'identical_duplicates':duplicates,'cancelled_cells':cancelled,'provider':data.get('provider')})
