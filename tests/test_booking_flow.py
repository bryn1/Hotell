"""Regression tests for the booking flow (MC 1286.1).

Covers the three audit-verified bugs (same-day free booking, reversed dates
with negative price, 500 on invalid date strings) plus the booking/cancel
flow and overlap rules the audit brief requires. Uses the shared `client`
fixture from conftest.py.
"""
from fastapi.testclient import TestClient


def _book(client: TestClient, room_id: int = 1, **overrides) -> dict:
    payload = {
        "guest_name": "Test Gast",
        "guest_email": "gast@example.com",
        "guest_phone": "",
        "check_in": "2026-10-01",
        "check_out": "2026-10-03",
    }
    payload.update(overrides)
    return client.post(f"/api/rooms/{room_id}/book", json=payload)


# --- The three audit bugs ---------------------------------------------------

def test_same_day_booking_rejected_400(client):
    # F1: check_in == check_out used to return 200 with total_price=0.
    resp = _book(client, check_in="2026-10-01", check_out="2026-10-01")
    assert resp.status_code == 400
    assert "efter" in resp.json()["detail"]


def test_check_out_before_check_in_rejected_400(client):
    # F2: check_out < check_in used to return 200 with a NEGATIVE total.
    resp = _book(client, check_in="2026-10-03", check_out="2026-10-01")
    assert resp.status_code == 400
    assert "efter" in resp.json()["detail"]


def test_invalid_date_format_rejected_400_not_500(client):
    # F3: "not-a-date" used to raise ValueError -> HTTP 500.
    resp = _book(client, check_in="not-a-date")
    assert resp.status_code == 400
    assert "Ogiltigt datumformat" in resp.json()["detail"]


def test_invalid_check_out_format_rejected_400_not_500(client):
    resp = _book(client, check_out="2026/10/03")
    assert resp.status_code == 400
    assert "Ogiltigt datumformat" in resp.json()["detail"]


# --- Valid booking math -----------------------------------------------------

def test_valid_booking_returns_exact_total(client):
    # Room 1 (seeded "101") costs 1200 kr/night; 2 nights => 2400.
    resp = _book(client, check_in="2026-10-01", check_out="2026-10-03")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_price"] == 2400
    assert body["status"] == "confirmed"


def test_booking_unknown_room_404(client):
    resp = _book(client, room_id=9999)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Room not found"


# --- Overlap rules ----------------------------------------------------------

def test_overlapping_confirmed_booking_rejected_400(client):
    assert _book(client, check_in="2026-10-01", check_out="2026-10-03").status_code == 200
    resp = _book(client, check_in="2026-10-02", check_out="2026-10-04")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Room not available for these dates"


def test_booking_starting_when_previous_ends_allowed(client):
    # Adjacency: previous ends 10-03, new starts 10-03 -> allowed.
    assert _book(client, check_in="2026-10-01", check_out="2026-10-03").status_code == 200
    resp = _book(client, check_in="2026-10-03", check_out="2026-10-05")
    assert resp.status_code == 200
    assert resp.json()["total_price"] == 2400


def test_booking_ending_when_next_starts_allowed(client):
    # Adjacency the other way: new ends 10-01, existing starts 10-01 -> allowed.
    assert _book(client, check_in="2026-10-01", check_out="2026-10-03").status_code == 200
    resp = _book(client, check_in="2026-09-29", check_out="2026-10-01")
    assert resp.status_code == 200


def test_cancelled_booking_does_not_block_rebooking(client):
    first = _book(client, check_in="2026-10-01", check_out="2026-10-03")
    assert first.status_code == 200
    booking_id = first.json()["id"]

    cancel = client.put(f"/api/bookings/{booking_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    resp = _book(client, check_in="2026-10-01", check_out="2026-10-03")
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"


# --- Booking list / detail / cancel ------------------------------------------

def test_list_bookings_returns_list(client):
    assert _book(client).status_code == 200
    resp = client.get("/api/bookings/")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["guest_email"] == "gast@example.com"


def test_get_booking_unknown_id_404(client):
    resp = client.get("/api/bookings/9999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Booking not found"


def test_cancel_unknown_booking_404(client):
    resp = client.put("/api/bookings/9999/cancel")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Booking not found"


def test_cancel_sets_status_cancelled(client):
    booking_id = _book(client).json()["id"]
    resp = client.put(f"/api/bookings/{booking_id}/cancel")
    assert resp.status_code == 200
    detail = client.get(f"/api/bookings/{booking_id}")
    assert detail.json()["status"] == "cancelled"


def test_recancel_cancelled_booking_returns_409(client):
    # State guard: re-cancelling an already-cancelled booking is a conflict,
    # not a silent 200.
    booking_id = _book(client).json()["id"]
    assert client.put(f"/api/bookings/{booking_id}/cancel").status_code == 200
    resp = client.put(f"/api/bookings/{booking_id}/cancel")
    assert resp.status_code == 409
    assert "already cancelled" in resp.json()["detail"]


def test_cancel_completed_booking_returns_409(client):
    # State guard: a completed booking must not be cancellable.
    booking_id = _book(client).json()["id"]
    # Move the booking into the completed state directly (no completion
    # endpoint exists in this demo). Use the SAME overridden session the
    # TestClient uses (conftest binds get_db to a tmp_path SQLite file).
    from app.database import get_db
    from app.models.booking import Booking
    from app.main import app
    db = next(app.dependency_overrides[get_db]())
    try:
        booking = db.query(Booking).filter(Booking.id == booking_id).first()
        booking.status = "completed"
        db.commit()
    finally:
        db.close()
    resp = client.put(f"/api/bookings/{booking_id}/cancel")
    assert resp.status_code == 409
    assert "Completed" in resp.json()["detail"]


def test_list_bookings_includes_room_number(client):
    # Fix: the bookings list carries the human room number ("201"), joined
    # server-side, while keeping room_id for backward compatibility.
    assert _book(client, room_id=1).status_code == 200
    body = client.get("/api/bookings/").json()
    assert len(body) == 1
    assert body[0]["room_id"] == 1
    assert body[0]["room_number"] == "101"


# --- Room creation -----------------------------------------------------------

def test_create_room_duplicate_room_number_rejected_400(client):
    payload = {
        "room_number": "101",  # already seeded
        "room_type": "double",
        "capacity": 2,
        "price_per_night": 1000,
    }
    resp = client.post("/api/rooms/", json=payload)
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"]
