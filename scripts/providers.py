"""Download authority products into portable, unmodified S-57 exchange directories."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import Request, urlopen
import zipfile

ELWIS = 'https://www.elwis.de/DE/dynamisch/IENC/'
RWS = 'https://www.vaarweginformatie.nl'
EURIS = 'https://www.eurisportal.eu'
USACE = 'https://ienccloud.us/ienc_s57.html'
NOAA = 'https://charts.noaa.gov/ENCs/'
PROFILES = {
    'noaa': ('NOAA ENC', 'Maritime ENC', 'NOAA Office of Coast Survey', NOAA + 'ENCs.shtml', [-74.01,40.69,13]),
    'de_wsv': ('German federal waterways', 'Inland ENC', 'Wasserstraßen- und Schifffahrtsverwaltung des Bundes (WSV), GeoNutzV', ELWIS, [13.322821,52.543987,18]),
    'nl_rws': ('Dutch inland and coastal waters', 'Inland ENC', 'Rijkswaterstaat, CC0', RWS + '/frp/page/infra_enc', [3.60626,51.440269,18]),
    'usace': ('US Army Corps of Engineers', 'Inland ENC', 'USACE Army Geospatial Center', USACE, [-80.015,40.441,15]),
    'be_coast': ('Belgian coast and waterways', 'Inland ENC', 'Flemish Hydrography and contributing authorities', EURIS + '/enc', [3.191318,51.349201,17]),
    'ro_danube': ('Lower Danube and Black Sea approaches', 'Inland ENC', 'Lower Danube River Administration and contributing authorities', EURIS + '/enc', [29.667537,45.157542,18]),
}


def sha(path):
    with path.open('rb') as stream:
        digest = hashlib.sha256()
        while block := stream.read(1024 * 1024):
            digest.update(block)
        return digest.hexdigest()


def download(url, destination=None):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={'User-Agent':'geoserver-enc-plugin/0.2'}), timeout=90) as response:
                if destination is None:
                    return response.read()
                with destination.open('wb') as out:
                    shutil.copyfileobj(response, out, 1024 * 1024)
                if response.headers.get('Content-Length') and destination.stat().st_size != int(response.headers['Content-Length']):
                    raise OSError('Incomplete download ' + url)
                return
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


class Links(HTMLParser):
    def __init__(self, url):
        super().__init__()
        self.urls = []
        self.url = url
        self.feed(download(url).decode('utf-8', errors='replace'))

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get('href')
        if tag == 'a' and href:
            self.urls.append(urljoin(self.url, href))


def products(provider, work, manifest):
    if provider == 'noaa':
        download(NOAA + 'ENCProdCat.xml', work / 'ENCProdCat.xml')
        manifest['noaa_catalogue'] = 'ENCProdCat.xml'
        manifest['inventory_source'] = NOAA + 'ENCProdCat.xml'
        return [('all', NOAA + 'All_ENCs.zip')]
    if provider == 'usace':
        links = Links(USACE).urls
        manifest['expected_cells'] = sorted({Path(urlsplit(u).path).stem for u in links
            if re.fullmatch(r'U[0-9A-Z]{7}\.zip', Path(urlsplit(u).path).name)})
        if not manifest['expected_cells']:
            raise ValueError('USACE cell list is empty')
        bulk, = {u for u in links if u.endswith('/ienc_s57.zip')}
        return [('all', bulk)]
    if provider == 'de_wsv':
        entries = []
        for detail in dict.fromkeys(u for u in Links(ELWIS).urls if '/IENC/Download?file=' in u):
            product = parse_qs(urlsplit(detail).query)['file'][0]
            url, = {u for u in Links(detail).urls if '/IENC/File:' in u}
            entries.append((product, url))
        return entries
    if provider == 'nl_rws':
        listing = json.loads(download(RWS + '/frp/api/webcontent/downloads?pageId=infra/enc'))
        entries = []
        for prefix in ('Nederland (excl', 'Zeeland met Diepte', 'Waddenzee met Diepte'):
            row, = [r for r in listing if r['name'].casefold().startswith(prefix.casefold())
                    and r['author'].casefold() in ('rijkswaterstaat', 'rws civ')]
            entries.append((prefix.split()[0], RWS + '/fdd/main/download?fileId=' + str(row['fileId'])))
        return entries
    country = {'be_coast':'BE', 'ro_danube':'RO'}[provider]
    listing = json.loads(download(EURIS + '/api/v3/ienc/export-files'))
    row, = [r for r in listing if r['countryCode'] == country]
    manifest['expected_base_count'] = row['mapCount']
    manifest['attribution'] += '. API/Service IENC incorporated from EuRIS (eurisportal.eu)'
    return [(country, EURIS + '/AWFIENC/api/IENC/DownloadIENCExportFile?country=' + country)]


def extract(archive, directory):
    with zipfile.ZipFile(archive) as z:
        seen = set()
        for info in z.infolist():
            p = PurePosixPath(info.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in info.filename or (info.external_attr >> 28) == 10:
                raise ValueError(f'Unsafe archive entry {p}')
            if p in seen and not info.is_dir():
                raise ValueError(f'Duplicate archive entry {p}')
            seen.add(p)
            z.extract(info, directory)


# The EuRIS export contains a truncated copy of this specific reissue. Use the
# partner portal only when both the damaged and the replacement bytes match.
def restore_danube_reissue(work, manifest, archive):
    original = next(work.rglob('3R7PAM02.000'), None)
    truncated = 'de64f200199068147443730b17ae9c369bb483f828e2c2fe297da7e290b07f9e'
    complete = '72b8331bb759f65197295f40057fcbe351bc6633bc00ba2b35d2e01346c8cfb0'
    if original is None or sha(original) != truncated:
        return
    url = 'https://www.danubeportal.com/application/cache/uploads/charts/electronic/RO/10/1726821665.zip'
    download(url, archive)
    with zipfile.ZipFile(archive) as z:
        member, = [name for name in z.namelist() if PurePosixPath(name).name == original.name]
        data = z.read(member)
    if hashlib.sha256(data).hexdigest() != complete:
        raise ValueError('Danube FIS replacement does not match the verified complete reissue')
    original.rename(original.with_suffix('.000.truncated'))
    original.write_bytes(data)
    manifest['restored_cells'] = [{'file':str(original.relative_to(work)), 'source':url,
        'archive_sha256':sha(archive), 'original_edition_update':'1/5', 'replacement_edition_update':'1/7', 'original_sha256':truncated, 'sha256':complete}]


def prepare(out, provider=None, archives=()):
    if out.exists():
        raise ValueError(f'Choose a new exchange directory: {out}')
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix='.enc-prepare-') as scratch:
        work = Path(scratch) / 'output'
        work.mkdir()
        manifest = {'format':'enc-exchange-1','prepared_utc':datetime.now(timezone.utc).isoformat(),'packages':[]}
        if provider:
            title, kind, attribution, site, view = PROFILES[provider]
            manifest.update(provider=provider,title=title,product=kind,attribution=attribution,source=site,view=view)
            inputs = products(provider, work, manifest)
        else:
            inputs = [(p.stem, p) for p in archives]
        if not inputs:
            raise ValueError('No exchange archives found')
        for i, (name, source) in enumerate(inputs, 1):
            print(f'Preparing {i}/{len(inputs)} {name}', flush=True)
            archive = source if isinstance(source, Path) else Path(scratch) / 'download.zip'
            if not isinstance(source, Path):
                download(source, archive)
            directory = f'package-{i:03d}'
            extract(archive, work / directory)
            manifest['packages'].append({'name':name,'source':str(source),'directory':directory,'sha256':sha(archive)})
        if provider == 'ro_danube':
            restore_danube_reissue(work, manifest, Path(scratch) / 'reissue.zip')
        if not next(work.rglob('*.000'), None):
            raise ValueError('Exchange contains no base cells')
        (work / 'exchange.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
        work.rename(out)
    print(out)
