#!/usr/bin/env python3
import os
import signal
import subprocess
import time

os.chdir('/Users/jefflau/projects/pdf_report_converter/PDF_converter')

try:
    result = subprocess.run(['lsof', '-ti', ':5000'], capture_output=True, text=True)
    pids = [p for p in result.stdout.strip().split('\n') if p]
    for pid in pids:
        try:
            os.kill(int(pid), signal.SIGKILL)
            print(f"Killed process {pid}")
        except:
            pass
    time.sleep(1)
except:
    pass

proc = subprocess.Popen(
    ['/Users/jefflau/anaconda3/bin/python3', '-m', 'http.server', '5000'],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)
print(f"Server started with PID {proc.pid} on port 5000")