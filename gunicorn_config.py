"""Gunicorn production configuration.

This file is imported by gunicorn. It tells gunicorn how to serve
the Flask application. The Flask code itself (app.py) is NOT modified.
"""

workers = 2

worker_class = 'sync'

timeout = 600

keepalive = 5

max_requests = 10
max_requests_jitter = 2

preload_app = True

bind = 'unix:/tmp/y4_report.sock'

accesslog = '/var/log/y4_report/access.log'
errorlog = '/var/log/y4_report/error.log'
loglevel = 'info'
