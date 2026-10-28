#!/usr/bin/env python3
"""vm106 service entrypoint for the Hotell booking app (MC 80.1 T2 / MC 1923 fix).

Runs the FastAPI app (app.main:app) with uvicorn, bound to 127.0.0.1:8117
(the manifest port for apps/hotell).

MC 1923: the renderer's hardened unit (ProtectSystem=strict, ProtectHome)
makes the whole git working copy read-only at runtime -- there was no
writable path anywhere under /var/www/portfolio. The fork's engine opens
SQLite at ./.data/hotel.db (app/config.py DB_URL) and app/main.py itself
unconditionally does os.makedirs("data", exist_ok=True) at import time --
both used to crash the unit (OSError 30, read-only) before the renderer
grew `StateDirectory=vm106-app-<name>` (systemd then creates and chowns
/var/lib/vm106-app-hotell to appsvc and exports $STATE_DIRECTORY to us).

If $STATE_DIRECTORY is set (it will be, under the fixed unit) we rebase
the DB and both data dirs there and never write inside the git tree:
  - app/config.py's Settings is pydantic BaseSettings, so DB_URL is
    already env-overridable (verified: setting the env var flips
    settings.DB_URL, no fork code change needed) -- we set it here to
    $STATE_DIRECTORY/.data/hotel.db before app.main is ever imported, so
    the lru_cache'd Settings() singleton picks it up on its one
    construction.
  - app/main.py's own `os.makedirs("data", exist_ok=True)` is untouched
    (not our fork's file to edit) -- a thin os.makedirs shim installed
    before uvicorn imports app.main redirects that ONE relative call to
    land under $STATE_DIRECTORY/data instead of the read-only repo.

With no $STATE_DIRECTORY (local dev, e.g. bare `python3 server.py` outside
the unit) behavior is unchanged: dirs are created next to the app, DB_URL
keeps its in-repo default.
"""
import os
import sys
import uvicorn

# WorkingDirectory is already the app dir under the real unit, but chdir
# here too so `python3 server.py` from anywhere (local dev) still resolves
# static/ and templates/ (used as bare relative paths by app/main.py).
APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)

PORT = 8117          # MUST match the `port` field in apps.yaml for apps/hotell
HOST = "127.0.0.1"   # renderer's hardened unit binds the service to loopback
APP  = "app.main:app"

STATE_DIR = os.environ.get("STATE_DIRECTORY")

if STATE_DIR:
    data_dir = os.path.join(STATE_DIR, "data")
    dotdata_dir = os.path.join(STATE_DIR, ".data")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(dotdata_dir, exist_ok=True)

    # Env-override picked up by app/config.py's BaseSettings on its first
    # (lru_cache'd) construction -- must be set before app.main/app.config
    # get imported, which happens when uvicorn.run() below loads "APP".
    os.environ.setdefault("DB_URL", f"sqlite:///{os.path.join(dotdata_dir, 'hotel.db')}")

    # Redirect app/main.py's own relative os.makedirs("data", ...) call
    # into the writable state dir, without touching that file.
    _real_makedirs = os.makedirs

    def _state_redirected_makedirs(name, mode=0o777, exist_ok=False):
        if name in ("data", "./data"):
            return _real_makedirs(data_dir, mode=mode, exist_ok=True)
        if name in (".data", "./.data"):
            return _real_makedirs(dotdata_dir, mode=mode, exist_ok=True)
        return _real_makedirs(name, mode=mode, exist_ok=exist_ok)

    os.makedirs = _state_redirected_makedirs
else:
    # local-dev fallback: unchanged behavior, dirs created next to the app
    os.makedirs(".data", exist_ok=True)
    os.makedirs("data", exist_ok=True)

if __name__ == "__main__":
    # reload=False: the service unit owns lifecycle; no file-watch overload.
    # proxy_headers=False (card 11550, W2b): uvicorn's DEFAULT is
    # proxy_headers=True with forwarded_allow_ips="127.0.0.1", and ALL
    # nginx/tunnel traffic here arrives from loopback — so uvicorn itself
    # rewrote scope["client"] from any X-Forwarded-For (peer trusted),
    # making demo_guard's socket-peer fallback attacker-controlled again
    # (one fresh XFF per request reset the visitor identity; audit W2b).
    # The app reads CF-Connecting-IP explicitly (app/demo_guard.py) and
    # must NOT let the server rewrite client identity from unauthenticated
    # XFF headers.
    uvicorn.run(APP, host=HOST, port=PORT, reload=False, log_level="info",
                proxy_headers=False)
