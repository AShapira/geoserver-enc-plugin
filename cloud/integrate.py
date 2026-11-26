#!/usr/bin/env python3
"""Add the ENC module to a clean, tagged upstream Cloud source checkout."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def integrate(cloud):
    tag = subprocess.check_output(['git','describe','--exact-match','--tags','HEAD'], cwd=cloud, text=True).strip()
    if tag not in ('v3.0.0','v3.0.2'):
        raise ValueError(f'Unsupported GeoServer Cloud release {tag}')
    formats = cloud/'src/extensions/input-formats'
    module = formats/'s57'
    vector = formats/'vector-formats/pom.xml'
    native = cloud/'src/apps/base-images/geoserver/Dockerfile'
    for path in (formats/'pom.xml', vector, native):
        subprocess.run(['git','diff','--quiet','HEAD','--',path], cwd=cloud, check=True)
    config = cloud/'config'
    routes = [config/'gateway.yml']
    if tag == 'v3.0.0':
        routes.append(config/'gateway-webflux.yml')
    route_anchor = '${basepath}/webresources/wms/**'
    for path in routes:
        subprocess.run(['git','diff','--quiet','HEAD','--',path.name], cwd=config, check=True)
        if path.read_text().count(route_anchor) != 1:
            raise ValueError(f'Unexpected WMS gateway route in {path}')
    if module.exists():
        raise FileExistsError(module)
    dependency = """    <dependency>
      <groupId>org.geoserver.cloud.extensions</groupId>
      <artifactId>gs-cloud-extension-s57</artifactId>
      <version>${revision}</version>
    </dependency>"""
    edits = [(formats/'pom.xml', '    <module>vector-formats</module>', '    <module>s57</module>'),
             (vector, '  <dependencies>', dependency)]
    for path, anchor, addition in edits:
        if path.read_text().count(anchor) != 1:
            raise ValueError(f'Unexpected module structure in {path}')
    shutil.copytree(ROOT/'src/main', module/'src/main')
    shutil.copytree(ROOT/'portrayal/upstream', module/'src/main/resources/org/enc/geoserver/s52')
    shutil.copy2(ROOT/'cloud/s57-pom.xml', module/'pom.xml')
    for notice in ('LICENSE', 'NOTICE.md'):
        shutil.copy2(ROOT/notice, module/'src/main/resources/META-INF'/notice)
    for path, anchor, addition in edits:
        path.write_text(path.read_text().replace(anchor, anchor+'\n'+addition))
    for path in routes:
        path.write_text(path.read_text().replace(route_anchor, route_anchor+',${basepath}/enc/viewer/**'))
    with native.open('a') as f:
        f.write('\nRUN apt-get update && apt-get install -y --no-install-recommends gdal-bin'
                ' && rm -rf /var/lib/apt/lists/* && ogrinfo --format S57'
                ' && ogrinfo --format GPKG && ogrinfo --format SQLite\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cloud_checkout', type=Path)
    integrate(parser.parse_args().cloud_checkout.resolve())
