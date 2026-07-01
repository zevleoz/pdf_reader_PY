#!/usr/bin/env python3
import os
import sys
import subprocess

env = os.environ.copy()
env.pop('TRAE_SANDBOX_CLI_PATH', None)
env.pop('TRAE_SANDBOX_STORAGE_PATH', None)
env.pop('TRAE_SANDBOX_CONFIG_NAME', None)

os.chdir('/Users/jefflau/projects/pdf_report_converter/PDF_converter')

proc = subprocess.Popen(
    [sys.executable, '-m', 'http.server', '5000'],
    env=env,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)
print(f"Server started on port 5000 with PID {proc.pid}")