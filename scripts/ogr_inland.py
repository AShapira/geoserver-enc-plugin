#!/usr/bin/env python3
"""Use the installed case-safe Inland ENC dictionary for catalogue conversions."""
import os
import subprocess
import sys

os.environ['S57_CSV'] = '/opt/enc/s57'
if sys.argv[1:] == ['--version']:
    print(subprocess.check_output(['/usr/bin/ogr2ogr','--version'],text=True).strip() + ' enc-inland-2')
else:
    os.execv('/usr/bin/ogr2ogr',['ogr2ogr',*sys.argv[1:]])
