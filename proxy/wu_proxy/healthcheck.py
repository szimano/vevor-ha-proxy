"""Docker HEALTHCHECK: exit 0 if /healthz answers."""
import os
import sys
import urllib.request

host = os.environ.get("BIND_HOST", "127.0.0.1")
if host == "0.0.0.0":
    host = "127.0.0.1"
port = os.environ.get("PORT", "80")
try:
    urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=2)
except Exception:
    sys.exit(1)
