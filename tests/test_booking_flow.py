"""Regression tests for the booking flow (MC 1286.1).

Covers the three audit-verified bugs (same-day free booking, reversed dates
with negative price, 500 on invalid date strings) plus the booking/cancel
flow and overlap rules the audit brief requires. Uses the shared `client`
and `book` fixtures from conftest.py; all valid range dates derive from
date.today() so the F8 past-date guard (MC 1310.1) cannot silently 422
them (MC 11534).
"""
from datetime import date, timedelta


# --- The three audit bugs ---------------------------------------------------

def test_same_day_booking_rejected_400(book):
    # F1: check_in == check_out used to return 200 with total_price=0.
    # Future range so the 400 comes from range validation, not the F8
    # guard; test_past_same_day_booking_rejected_422 covers that split.
    resp = book(check_in=book.base_in.isoformat(), check_out=book.base_in.isoformat())
    assert resp.status_code == 400
    assert "efter" in resp.json()["detail"]


def test_past_same_day_booking_rejected_422(book):
    # MC 11534 split: a past check_in makes the F8 guard win with 422
    # before the 400 range validation can run.
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    resp = book(check_in=yesterday, check_out=yesterday)
    assert resp.status_code == 422


def test_check_out_before_check_in_rejected_400(book):
    # F2: check_out < check_in used to return 200 with a NEGATIVE total.
    # Future pair so the 400 is range validation, not the F8 guard.
    resp = book(check_in=book.base_out.isoformat(), check_out=book.base_in.isoformat())
    assert resp.status_code == 400
    assert "efter" in resp.json()["detail"]


def test_past_reversed_dates_rejected_422(book):
    # MC 11534 split: reversed AND in the past -> the F8 guard wins (422).
    resp = book(
        check_in=(date.today() - timedelta(days=3)).isoformat(),
        check_out=(date.today() - timedelta(days=5)).isoformat(),
    )
    assert resp.status_code == 422


def test_invalid_date_format_rejected_400_not_500(book):
    # F3: "not-a-date" used to raise ValueError -> HTTP 500. The format
    # check runs before the F8 guard, so this stays a 400 on any date.
    resp = book(check_in="not-a-date")
    assert resp.status_code == 400
    assert "Ogiltigt datumformat" in resp.json()["detail"]


def test_invalid_check_out_format_rejected_400_not_500(book):
    # Slash-separated date: invalid under YYYY-MM-DD, so the format check
    # (a 400) fires before the F8 guard regardless of the base dates.
    resp = book(check_out="2026/10/03")
    assert resp.status_code == 400
    assert "Ogiltigt datumformat" in resp.json()["detail"]


# --- Valid booking math -----------------------------------------------------

def test_valid_booking_returns_exact_total(book):
    # Room 1 (seeded "101") costs 1200 kr/night; 2 nights => 2400.
    resp = book()
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_price"] == 2400
    assert body["status"] == "confirmed"


def test_booking_unknown_room_404(book):
    # The room-exists guard runs before any date handling, date-independent.
    resp = book(room_id=9999)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Room not found"


# --- Overlap rules ----------------------------------------------------------

def test_overlapping_confirmed_booking_rejected_400(book):
    assert book().status_code == 200
    resp = book(
        check_in=(book.base_in + timedelta(days=1)).isoformat(),
        check_out=(book.base_out + timedelta(days=1)).isoformat(),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Room not available for these dates"


def test_booking_starting_when_previous_ends_allowed(book):
    # Adjacency: previous ends base_out, new starts base_out -> allowed.
    assert book().status_code == 200
    resp = book(
        check_in=book.base_out.isoformat(),
        check_out=(book.base_out + timedelta(days=2)).isoformat(),
    )
    assert resp.status_code == 200
    assert resp.json()["total_price"] == 2400


def test_booking_ending_when_next_starts_allowed(book):
    # Adjacency the other way: new ends base_in, existing starts base_in.
    assert book().status_code == 200
    resp = book(
        check_in=(book.base_in - timedelta(days=2)).isoformat(),
        check_out=book.base_in.isoformat(),
    )
    assert resp.status_code == 200


def test_cancelled_booking_does_not_block_rebooking(client, book):
    first = book()
    assert first.status_code == 200
    booking_id = first.json()["id"]

    # Ownership token from the booking-success response (card 11535).
    cancel = client.put(
        f"/api/bookings/{booking_id}/cancel",
        headers={"X-Cancel-Token": first.json()["cancel_token"]},
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    resp = book()
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"


# --- Booking list / detail / cancel ------------------------------------------

def test_list_bookings_returns_list(client, book):
    assert book().status_code == 200
    resp = client.get("/api/bookings/")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1
    # Read-minimization (card 11535): the list carries the guest NAME for
    # the demo list, but never the e-mail.
    assert body[0]["guest_name"] == "Test Gast"
    assert "guest_email" not in body[0]


def test_get_booking_unknown_id_404(client):
    resp = client.get("/api/bookings/9999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Booking not found"


def test_cancel_unknown_booking_404(client):
    resp = client.put("/api/bookings/9999/cancel")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Booking not found"


def test_cancel_sets_status_cancelled(client, book):
    created = book().json()
    resp = client.put(
        f"/api/bookings/{created['id']}/cancel",
        headers={"X-Cancel-Token": created["cancel_token"]},
    )
    assert resp.status_code == 200
    detail = client.get(f"/api/bookings/{created['id']}")
    assert detail.json()["status"] == "cancelled"


def test_recancel_cancelled_booking_returns_409(client, book):
    # State guard: re-cancelling an already-cancelled booking is a conflict,
    # not a silent 200.
    created = book().json()
    headers = {"X-Cancel-Token": created["cancel_token"]}
    assert client.put(f"/api/bookings/{created['id']}/cancel", headers=headers).status_code == 200
    resp = client.put(f"/api/bookings/{created['id']}/cancel", headers=headers)
    assert resp.status_code == 409
    assert "already cancelled" in resp.json()["detail"]


def test_cancel_completed_booking_returns_409(client, book):
    # State guard: a completed booking must not be cancellable.
    book_response = book().json()
    booking_id = book_response["id"]
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
    resp = client.put(
        f"/api/bookings/{booking_id}/cancel",
        headers={"X-Cancel-Token": book_response["cancel_token"]},
    )
    assert resp.status_code == 409
    assert "Completed" in resp.json()["detail"]


def test_list_bookings_includes_room_number(client, book):
    # Fix: the bookings list carries the human room number ("201"), joined
    # server-side, while keeping room_id for backward compatibility.
    assert book(room_id=1).status_code == 200
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
