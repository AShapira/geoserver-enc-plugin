#!/usr/bin/env python3
"""Stop only Java processes belonging to this workspace's dedicated demo runtime."""
from pathlib import Path
import os
import signal
ROOT=Path(__file__).resolve().parents[1]
marker=('-DGEOSERVER_DATA_DIR='+str(ROOT/'.runtime/geoserver/data_dir')).encode()
java=str(ROOT/'.runtime/env/bin/java').encode()
found=False
for p in Path('/proc').glob('[0-9]*'):
    try:
        args=(p/'cmdline').read_bytes().split(b'\0')
        if args and args[0]==java and marker in args:
            os.kill(int(p.name),signal.SIGTERM)
            print('Requested shutdown of demo GeoServer PID',p.name)
            found=True
    except (PermissionError,FileNotFoundError,ProcessLookupError):
        continue
if not found: print('No running GeoServer from this demo runtime was found.')
