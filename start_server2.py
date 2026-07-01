#!/usr/bin/env python3
import os
import sys

os.chdir('/Users/jefflau/projects/pdf_report_converter/PDF_converter')
os.execl(sys.executable, sys.executable, '-m', 'http.server', '5000')