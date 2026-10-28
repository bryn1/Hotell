"""Wave-1 security-fix regression tests (card 11535, audit 202610271433).

Covers the five W2 backend fixes end to end: (a) PII read-minimization on
the bookings endpoints, (b) the cancel_token ownership contract, (c) the
guard's CF-Connecting-IP-only identity (a spoofed X-Forwarded-For no longer
buys a fresh bucket), (d) fail-closed bucket pruning, and (e) the calendar
year+December boundary — plus (f) the W2b server-layer completion (card
11550): the guard's peer fallback under REAL uvicorn protocol semantics,
where uvicorn's default forwarded-header rewriting must stay disabled.
Booking dates derive from date.today() through the shared `book` fixture
(the MC 11534 date-portability pattern); the calendar probes stay literal on
purpose — they encode the 9999/10000 year boundary, not current dates.
"""
import re
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import demo_guard
from app.database import Base, get_db
from app.demo_guard import DemoWriteGuard
from app.main import app
from app.models.booking import Booking


# --- (a) PII read-minimization -----------------------------------------------

BOOKING_KEYS = {
    "id", "guest_name", "room_id", "room_number",
    "check_in", "check_out", "total_price", "status",
}


def test_list_bookings_exact_allowed_keys_no_pii(client, book):
    assert book().status_code == 200
    body = client.get("/api/bookings/").json()
    assert set(body[0].keys()) == BOOKING_KEYS
    assert "cancel_token" not in body[0]  # returned ONLY by the book response


def test_get_booking_exact_allowed_keys_no_pii(client, book):
    booking_id = book().json()["id"]
    body = client.get(f"/api/bookings/{booking_id}").json()
    assert set(body.keys()) == BOOKING_KEYS
    assert "cancel_token" not in body


def test_book_response_carries_token_and_no_email(book):
    # The booking-success response is the single place cancel_token ever
    # appears; guest_email stays in the DB and never comes back.
    body = book().json()
    assert body["cancel_token"]
    assert "guest_email" not in body
    assert "guest_phone" not in body


# --- (b) cancel ownership ------------------------------------------------------

def test_cancel_requires_the_ownership_token(client, book):
    created = book().json()
    url = f"/api/bookings/{created['id']}/cancel"
    assert client.put(url).status_code == 403  # missing header
    wrong = client.put(url, headers={"X-Cancel-Token": "fel-token"})
    assert wrong.status_code == 403
    ok = client.put(url, headers={"X-Cancel-Token": created["cancel_token"]})
    assert ok.status_code == 200
    assert ok.json() == {"status": "cancelled"}


def test_cancel_403_message_is_swedish(client, book):
    created = book().json()
    resp = client.put(f"/api/bookings/{created['id']}/cancel")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Du kan bara avboka dina egna bokningar"


def test_legacy_null_token_row_cancels_without_header(client, book):
    # Rows stored before the fix carry cancel_token NULL and keep the old
    # any-caller behaviour (legacy demo allowance, see routers/bookings.py).
    from app.database import get_db as _get_db
    db = next(app.dependency_overrides[_get_db]())
    try:
        legacy = Booking(
            guest_name="Legacy Gast",
            guest_email="legacy@example.com",
            room_id=1,
            check_in=book.base_in,
            check_out=book.base_out,
            total_price=2400,
            status="confirmed",
            cancel_token=None,
        )
        db.add(legacy)
        db.commit()
        legacy_id = legacy.id
    finally:
        db.close()
    resp = client.put(f"/api/bookings/{legacy_id}/cancel")
    assert resp.status_code == 200
    assert resp.json() == {"status": "cancelled"}


# --- (c) guard identity: XFF spoof no longer bypasses --------------------------


@pytest.fixture()
def guard_client(tmp_path):
    """TestClient WITH the DemoWriteGuard active.

    The shared `client` fixture strips the guard (those tests make many
    back-to-back writes); these tests are about the guard, so the middleware
    is re-added here — and stripped again at teardown so module order stays
    irrelevant. Each TestClient builds a fresh stack, hence fresh buckets.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path}/guard_hotell.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.middleware_stack = None
    app.add_middleware(DemoWriteGuard)
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.user_middleware[:] = [
            m for m in app.user_middleware if m.cls is not DemoWriteGuard
        ]
        app.middleware_stack = None
        app.dependency_overrides.clear()
        engine.dispose()


def _thirteen_writes(client, extra_headers):
    # PUT cancel of a nonexistent id: a write the guard must count even
    # though the handler only ever answers 404 — no booking state needed.
    return [
        client.put("/api/bookings/9999/cancel", headers=extra_headers(i)).status_code
        for i in range(13)
    ]


def _assert_429_from_write_eleven(statuses):
    # CAPACITY is 10: writes 1..10 pass through (404 from the handler),
    # writes 11..13 are throttled by the guard.
    cap = demo_guard.CAPACITY
    assert statuses[:cap] == [404] * cap
    assert statuses[cap:] == [429] * (13 - cap)


def test_xff_spoof_no_longer_buys_fresh_buckets(guard_client):
    # One client, 13 writes, a FRESH X-Forwarded-For on every request: the
    # old identity code trusted the first XFF entry, so each write looked
    # like a new visitor and nothing ever throttled. Now XFF is not trusted
    # at all — all writes share the socket-peer bucket and the limit bites.
    statuses = _thirteen_writes(
        guard_client, lambda i: {"X-Forwarded-For": f"198.51.100.{i}"}
    )
    _assert_429_from_write_eleven(statuses)


def test_control_honest_bucket_also_429s(guard_client):
    # Control leg (same bucket, honest client): the identical pattern with
    # no headers throttles exactly the same — proof it is the shared
    # identity, not the spoof, that produces the 429s.
    _assert_429_from_write_eleven(_thirteen_writes(guard_client, lambda i: {}))


# --- (d) pruning is fail-closed for spent buckets -------------------------------


def test_prune_never_revives_a_spent_bucket():
    # Unit probe of the real middleware (no HTTP): exhaust one visitor,
    # then flood MORE than MAX_TRACKED fresh identities through _take. The
    # old wholesale .clear() reset everything and handed the spent bucket a
    # full refill back (audit P1 fail-open).
    guard = DemoWriteGuard(None)
    victim = "203.0.113.50"
    for _ in range(demo_guard.CAPACITY):
        assert guard._take(victim) is True
    assert guard._take(victim) is False  # spent
    for i in range(demo_guard.MAX_TRACKED + 2):
        assert guard._take(f"198.51.100.{i}") is True
    # The memory bound holds (the take that inserts after a prune can sit
    # one above the cap until the next take prunes again)...
    assert len(guard._buckets) <= demo_guard.MAX_TRACKED + 1
    # ...and the spent bucket survived the flood: still no token. Fail-closed.
    assert guard._take(victim) is False


# --- (e) calendar year+December boundary -----------------------------------------


def test_calendar_9999_december_400_both_endpoints(client):
    # date(9999+1, 1, 1) overflows: the combination must be a 400, never 500.
    resp = client.get("/api/calendar/9999/12")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "År och månad kan inte kombineras"
    assert client.get("/api/calendar/9999/12/rooms/1").status_code == 400


def test_calendar_9999_january_still_valid(client):
    # Neighbour unchanged: MAX_YEAR itself is fine, only the December
    # combination overflows.
    assert client.get("/api/calendar/9999/1").status_code == 200


def test_calendar_year_10000_still_400(client):
    assert client.get("/api/calendar/10000/1").status_code == 400


# --- (f) uvicorn forwarded-header trust (card 11550, W2b) ---------------------
# uvicorn's default is proxy_headers=True with forwarded_allow_ips
# "127.0.0.1": behind nginx (peer 127.0.0.1) it rewrites scope["client"]
# from any X-Forwarded-For, so the guard's socket-peer fallback was
# forgeable at the SERVER layer even after W2 fixed the app layer. These
# legs run the real app under real uvicorn protocol semantics on a random
# free port — TestClient cannot see this class at all: it never executes
# uvicorn's h11 forwarded-header handling.


@pytest.fixture()
def live_uvicorn(tmp_path):
    """Start the app under a real uvicorn server; the factory yields the port.

    Fresh DB + fresh guard (fresh buckets) per server; one server per test
    keeps the shared app's middleware stack exact. Teardown mirrors the
    guard_client fixture: strip the guard, reset the cached stack.
    """
    started = []

    def _start(proxy_headers: bool) -> int:
        engine = create_engine(
            f"sqlite:///{tmp_path}/live_hotell.db",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=engine)
        TestingSession = sessionmaker(bind=engine)

        def override_get_db():
            db = TestingSession()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        app.middleware_stack = None
        app.add_middleware(DemoWriteGuard)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=port,
            log_level="critical", proxy_headers=proxy_headers,
        ))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        started.append((server, thread, engine))
        deadline = time.monotonic() + 10.0
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("uvicorn did not start on the probe port")
            time.sleep(0.05)
        return port

    yield _start

    for server, thread, engine in started:
        server.should_exit = True
        thread.join(10)
        engine.dispose()
    app.user_middleware[:] = [
        m for m in app.user_middleware if m.cls is not DemoWriteGuard
    ]
    app.middleware_stack = None
    app.dependency_overrides.clear()


def _thirteen_writes_http(port, extra_headers):
    # Same 13-write probe as _thirteen_writes, over real HTTP against the
    # uvicorn server (PUT cancel of a nonexistent id: the guard counts it,
    # the handler only ever answers 404).
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as c:
        return [
            c.put("/api/bookings/9999/cancel", headers=extra_headers(i)).status_code
            for i in range(13)
        ]


def test_fresh_xff_throttles_under_real_uvicorn(live_uvicorn):
    # THE FIX leg: proxy_headers=False (what server.py/run.py now pass).
    # Fresh X-Forwarded-For per write, but the socket peer stays real, so
    # all 13 writes share one bucket and the guard throttles from #11.
    port = live_uvicorn(proxy_headers=False)
    statuses = _thirteen_writes_http(
        port, lambda i: {"X-Forwarded-For": f"10.9.9.{i}"}
    )
    _assert_429_from_write_eleven(statuses)


def test_fresh_xff_bypasses_when_proxy_headers_enabled(live_uvicorn):
    # Mechanism leg — proves the fix leg can go red: flipping the ONE flag
    # back to uvicorn's default re-enables the rewrite (loopback peer is in
    # forwarded_allow_ips), every write looks like a new visitor and nothing
    # ever throttles. This is the exact W2b live finding of 00:02Z, encoded.
    port = live_uvicorn(proxy_headers=True)
    statuses = _thirteen_writes_http(
        port, lambda i: {"X-Forwarded-For": f"10.9.9.{i}"}
    )
    assert statuses == [404] * 13  # never throttled — the bypass, verbatim


def test_all_uvicorn_entrypoints_disable_proxy_headers():
    # Static pin of EVERY uvicorn caller (server.py prod, run.py dev, the
    # README dev command): a fix at one entrypoint only is how W2b happened
    # — W2 left uvicorn's own default in place behind nginx. The behavioural
    # legs carry their own flag; this is what goes red if a caller regresses.
    root = Path(__file__).resolve().parents[1]
    call_has_optout = re.compile(
        r"uvicorn\.run\([^)]*\bproxy_headers\s*=\s*False", re.S
    )
    for fname in ("server.py", "run.py"):
        assert call_has_optout.search((root / fname).read_text()), (
            f"{fname} must pass proxy_headers=False to uvicorn.run"
        )
    assert "--no-proxy-headers" in (root / "README.md").read_text()
