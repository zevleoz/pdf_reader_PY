#!/usr/bin/env python3
import os
import subprocess

os.chdir('/Users/jefflau/projects/pdf_report_converter/PDF_converter')

proc = subprocess.Popen(
    ['/Users/jefflau/anaconda3/bin/python3', '-m', 'http.server', '8888'],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)
print(f"Server started on port 8888, PID {proc.pid}")