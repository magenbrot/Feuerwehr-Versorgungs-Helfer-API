"""
Gunicorn configuration file for Feuerwehr-Versorgungs-Helfer.
"""

# pylint: disable=invalid-name

import multiprocessing

# Bind to all interfaces on the container's port
# The port will be overridden by the CMD in Dockerfile if needed
bind = "0.0.0.0:5000"

# Worker configuration
#workers = 1
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "gevent"

# Logging configuration
# '-' means log to stdout/stderr
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Custom log format to include request time
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" [%(L)ss]'

# Preload app for better performance
preload_app = True
