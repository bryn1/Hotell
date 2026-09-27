"""Regression tests for MC 1310.1 audit fix F9: hardcoded /hotell/ paths.

F9 (LOW, audit 1290.1): templates/index.html and static/js hardcoded 26+
"/hotell/" asset/API references, so bare `python run.py` (app served at /)
rendered an unstyled, broken page locally — every /hotell/static/* request
404'd. The deployed vm106 model mounts the app behind the /hotell/ prefix
(nginx proxy_pass), so the fix must work in BOTH modes:

- bare: app served at /, assets at /static/...
- prefixed: app served at /hotell/, assets at /hotell/static/...

Mechanism: the frontend derives its base path from the served index.html URL
(document.baseURI) instead of hardcoding /hotell/, and the app honours the
ASGI root_path so a prefixed mount rewrites asset URLs correctly.
"""
import re

from fastapi.testclient import TestClient


def _assert_no_hardcoded_hotell(html: str) -> None:
    matches = re.findall(r'(?:src|href)="[^"]*/hotell/', html)
    assert not matches, f"hardcoded /hotell/ references remain: {matches}"


def test_index_html_has_no_hardcoded_hotell_asset_paths():
    # Static check on the source file itself (the DoD bar).
    with open("templates/index.html", encoding="utf-8") as f:
        html = f.read()
    _assert_no_hardcoded_hotell(html)


def test_index_html_has_no_hardcoded_hotell_in_js():
    for js in ["static/js/utils/api.js", "static/js/app.js",
               "static/js/ui/render-rooms.js"]:
        with open(js, encoding="utf-8") as f:
            content = f.read()
        assert "/hotell/" not in content, f"{js} still hardcodes /hotell/"


def test_api_constructing_js_has_no_hardcoded_hotell_literal():
    # F9 extension: every JS file that constructs API URLs must derive its
    # base from document.baseURI (utils/api.js API_BASE / app.js API) — no
    # hardcoded "/hotell" string literal may remain anywhere in them.
    api_js = [
        "static/js/app.js",
        "static/js/utils/api.js",
        "static/js/ui/booking-flow.js",
        "static/js/ui/render-bookings.js",
        "static/js/ui/render-calendar.js",
        "static/js/ui/render-rooms.js",
    ]
    for js in api_js:
        with open(js, encoding="utf-8") as f:
            content = f.read()
        assert '"/hotell"' not in content, f"{js} hardcodes the \"/hotell\" literal"
        assert "'/hotell'" not in content, f"{js} hardcodes the '/hotell' literal"
        assert "/hotell/" not in content, f"{js} still hardcodes /hotell/"


def test_app_js_api_base_is_derived_not_hardcoded():
    # app.js must derive API from the served base path (document.baseURI),
    # matching the utils/api.js mechanism.
    with open("static/js/app.js", encoding="utf-8") as f:
        content = f.read()
    assert "document.baseURI" in content, (
        "app.js API base must be derived from document.baseURI"
    )


def test_bare_serving_assets_resolve(client):
    # Bare run.py mode: index served at /, assets must resolve WITHOUT prefix.
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    _assert_no_hardcoded_hotell(html)
    # Every local asset URL the page references must be fetchable at /.
    # The F9 fix intentionally uses RELATIVE URLs (static/css/...), so collect
    # both absolute and relative forms and normalise to absolute paths
    # (prepend '/' when missing) before fetching.
    raw_urls = re.findall(r'(?:src|href)="([^"]+)"', html)
    asset_urls = []
    for url in raw_urls:
        if url.startswith(("http://", "https://", "//", "data:", "#", "mailto:")):
            continue
        asset_urls.append(url if url.startswith("/") else f"/{url}")
    assert asset_urls, "index.html must reference local assets"
    for url in asset_urls:
        r = client.get(url)
        assert r.status_code == 200, f"asset {url} -> {r.status_code} in bare mode"


def test_prefixed_serving_assets_resolve():
    # Deployed mode: app mounted under /hotell/ (as nginx does on vm106).
    from app.main import app
    from fastapi.testclient import TestClient as TC
    prefixed = TC(app, root_path="/hotell")
    resp = prefixed.get("/hotell/")
    assert resp.status_code == 200
    html = resp.text
    _assert_no_hardcoded_hotell(html)
    # Assets referenced by the prefixed page must resolve under the prefix.
    asset_urls = re.findall(r'(?:src|href)="([^"]+)"', html)
    for url in asset_urls:
        if url.startswith(("http://", "https://", "//", "data:", "#", "mailto:")):
            continue
        r = prefixed.get(url if url.startswith("/") else f"/hotell/{url}")
        assert r.status_code == 200, f"asset {url} -> {r.status_code} in prefixed mode"
