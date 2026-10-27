"""Shared fixtures for the Hotell API tests.

Extracted from tests/test_rooms_api.py (MC 1286.1): the file-backed SQLite
+ TestClient fixture pattern is reused by every test module, so it lives here.
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.seed import seed_rooms
from app.main import app


@pytest.fixture()
def client(tmp_path):
    # File-backed SQLite (in-memory would be a fresh empty DB per connection).
    engine = create_engine(
        f"sqlite:///{tmp_path}/test_hotell.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    seed_rooms(session)
    session.close()

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # Bypass the DemoWriteGuard rate limiter (MC 2034.2): these tests make many
    # back-to-back writes from one "visitor" and target booking logic, not the
    # limiter. Removing the middleware is the cleanest way to disable it.
    from app.demo_guard import DemoWriteGuard
    app.user_middleware[:] = [
        m for m in app.user_middleware if m.cls is not DemoWriteGuard
    ]
    # Audit F4 (MC 1290.2): Starlette caches app.middleware_stack on the first
    # request; without resetting it, removing DemoWriteGuard from
    # user_middleware has no effect if another test module already made a
    # request -> order-dependent 429s. Reset so the middleware list is rebuilt.
    app.middleware_stack = None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture()
def book(client):
    """Shared booking POST with a future-dated default range (MC 11534).

    De-duplicates the three byte-identical _book helpers. Their hardcoded
    2026-10-01/03 defaults were a time bomb: the F8 past-date guard
    (app/routers/rooms.py) answers 422 for any check_in before today, so
    every hardcoded booking failed from 2026-10-02. Base dates derive from
    date.today() (the pattern test_f8_past_dates.py already used); tests
    override them, including with past dates on purpose for the guard.
    base_in/base_out are exposed as date objects so tests can build
    adjacent or overlapping ranges from the same anchor.
    """
    base_in = date.today() + timedelta(days=30)
    base_out = base_in + timedelta(days=2)

    def _book(room_id: int = 1, **overrides):
        payload = {
            "guest_name": "Test Gast",
            "guest_email": "gast@example.com",
            "guest_phone": "",
            "check_in": base_in.isoformat(),
            "check_out": base_out.isoformat(),
        }
        payload.update(overrides)
        return client.post(f"/api/rooms/{room_id}/book", json=payload)

    _book.base_in = base_in
    _book.base_out = base_out
    return _book
