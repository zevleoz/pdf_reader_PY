#!/usr/bin/env python3
import http.server
import socketserver
import os
import signal
import sys

os.chdir('/Users/jefflau/projects/pdf_report_converter/PDF_converter')

PORT = 5000

for pid in [655]:
    try:
        os.kill(pid, signal.SIGKILL)
        print(f"Killed PID {pid}")
    except:
        pass

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"Serving on port {PORT}")
    httpd.serve_forever()