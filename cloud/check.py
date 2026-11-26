#!/usr/bin/env python3
"""Verify two WMS replicas and a writer restart in a dedicated pgconfig test project."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def run(args):
    engine = os.environ.get('CONTAINER_ENGINE', 'podman')

    def container(service, number=1):
        labels = ['--filter', 'label=com.docker.compose.project='+args.project,
                  '--filter', 'label=com.docker.compose.service='+service]
        names = sorted(subprocess.check_output([engine,'ps',*labels,'--format','{{.Names}}'],text=True).split())
        return names[number-1]

    def execute(name, *cmd):
        return subprocess.check_output([engine, 'exec', name, *cmd])

    writer = container('rest')
    replicas = [container('wms', i) for i in (1,2)]
    checks = [sys.executable, str(ROOT/'scripts/check_installation.py'), '--url', args.url]
    def through_gateway(options):
        # The management endpoint becomes ready before discovery has refreshed gateway routes.
        for attempt in range(30):
            result = subprocess.run(checks + options, capture_output=True, text=True)
            if result.returncode == 0:
                return json.loads(result.stdout)
            transient = any(token in result.stderr for token in (
                '502', '503', 'Connection refused', 'Connection reset', 'Web UI did not list',
                'Expected 1530 global ENC styles', 'Remote end closed connection'))
            if not transient or attempt == 29:
                raise RuntimeError(result.stderr)
            time.sleep(3)
    before = through_gateway(['--publish'])
    if args.require_miss and before['first_tile'] != 'MISS':
        raise RuntimeError('Expected a freshly rendered tile in a clean project')
    services = {}
    for service in ('rest','webui','wfs','wms','gwc'):
        info, = json.loads(subprocess.check_output([engine,'inspect',container(service)]))
        if not info['Config']['Image'].endswith(':'+args.tag) or any(m['Destination'].startswith(
                ('/opt/additional_libs','/opt/app/bin')) for m in info['Mounts']):
            raise RuntimeError('Unexpected service image or classpath mount: '+service)
        jar = execute(container(service),'sha256sum','/opt/app/bin/BOOT-INF/lib/gs-s57.jar').decode().split()[0]
        services[service] = {'image':info['Image'], 'plugin_sha256':jar}
    def compare(report):
        for replica in replicas:
            data = execute(replica,'curl','-fsS','http://localhost:8080'+report['wms_query'])
            if hashlib.sha256(data).hexdigest() != report['wms_sha256']:
                raise ValueError('Renderer response differs: '+replica)
    compare(before)
    audit = "import glob,sqlite3; print([int(sqlite3.connect(p).execute('select DSID_UPDN from DSID').fetchone()[0]) for p in glob.glob('/enc-cache/*.gpkg')])"
    updates = json.loads(execute(writer,'python3','-c',audit))
    if 1 not in updates:
        raise ValueError('Update 1 missing from served snapshots')
    subprocess.run([engine,'restart',writer,replicas[0]],check=True,stdout=subprocess.DEVNULL)
    for instance in (writer, replicas[0]):
        for _ in range(120):
            if subprocess.run([engine,'exec',instance,'curl','-fsS','http://localhost:8081/actuator/health'],
                              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode == 0:
                break
            time.sleep(2)
        else:
            raise TimeoutError(instance)
    after = through_gateway([])
    compare(after)
    for key in ('styles','wms_sha256','tile_sha256','features'):
        if before[key] != after[key]:
            raise ValueError('Changed after restart: '+key)
    print(json.dumps({'tag':args.tag,'services':services,'gdal':execute(writer,'ogr2ogr','--version').decode().strip(),
                      'applied_updates':updates,'before':before,'after':after,'matching_wms_replicas':2},indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True, choices=['3.0.0','3.0.2'])
    parser.add_argument('--project', required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--require-miss', action='store_true')
    run(parser.parse_args())
