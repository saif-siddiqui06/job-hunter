# PythonAnywhere WSGI config for Apply Rocket.
# Paste this into the WSGI configuration file linked on the Web tab, replacing YOUR_USERNAME.
# Settings (Gemini key, invite code, data folder) are read from job-hunter/.env by app.py.
import os
import sys

APP_DIR = "/home/YOUR_USERNAME/job-hunter"

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

from app import app as application  # noqa: E402
