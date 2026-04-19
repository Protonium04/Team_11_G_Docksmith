#!/usr/bin/env python3
# sample_app/app.py
# Docksmith sample application — demonstrates all 6 Docksmithfile instructions

import os
import sys

APP_NAME = os.environ.get("APP_NAME", "docksmith-sample")
GREETING = os.environ.get("GREETING", "Hello")

print("=" * 50)
print(f"  {GREETING} from {APP_NAME}!")
print("=" * 50)
print(f"  Python  : {sys.version.split()[0]}")
print(f"  CWD     : {os.getcwd()}")
print(f"  PATH    : {os.environ.get('PATH', 'not set')[:60]}")
print()

# List files in /app to show COPY worked
app_dir = "/app"
if os.path.exists(app_dir):
    files = sorted(os.listdir(app_dir))
    print(f"  Files in {app_dir}:")
    for f in files:
        print(f"    - {f}")
else:
    print("  (running outside container)")

print()
print("  Docksmith container runtime: OK")
print("=" * 50)
