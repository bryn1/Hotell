"""Regression tests for the MC 1290.2 audit fixes (findings F1, F3, F5, F7).

F2 (stored XSS) is a frontend render-time fix in static/js — covered by the
manual/spot verification noted in the evidence file, not by the pytest suite.
F4 (test-order dependency) is covered by running the suite in both orders.
Booking dates derive from date.today() via the shared `book` fixture so the
F8 past-date guard (MC 1310.1) cannot silently 422 them (MC 11534).
"""
from datetime import date, timedelta


# --- F3: calendar must 400 (not 500) on invalid year/month -------------------

def test_calendar_invalid_month_400_not_500(client):
    resp = client.get("/api/calendar/2027/13")
    assert resp.status_code == 400
    assert "Månad" in resp.json()["detail"]


def test_calendar_month_zero_400(client):
    assert client.get("/api/calendar/2027/0").status_code == 400


def test_calendar_negative_month_400(client):
    assert client.get("/api/calendar/-1/5").status_code == 400


def test_calendar_absurd_year_400_not_500(client):
    assert client.get("/api/calendar/100000/5").status_code == 400


def test_calendar_year_zero_400(client):
    assert client.get("/api/calendar/0/5").status_code == 400


def test_calendar_room_endpoint_invalid_month_400(client):
    resp = client.get("/api/calendar/2027/13/rooms/1")
    assert resp.status_code == 400


def test_calendar_valid_month_still_works(client):
    # Derived future month: the endpoint answers for any year in 1..9999,
    # but a hardcoded 2027-10 would read as a stale date (MC 11534).
    cal = date.today().replace(day=1) + timedelta(days=365)
    resp = client.get(f"/api/calendar/{cal.year}/{cal.month}")
    assert resp.status_code == 200
    assert resp.json()["month"] == f"{cal.year:04d}-{cal.month:02d}"


# --- F5: server-side validation ----------------------------------------------

def test_booking_empty_guest_name_rejected_400(book):
    # Guest validation runs before the date guards: a 400 on any date.
    resp = book(guest_name="")
    assert resp.status_code == 400


def test_booking_whitespace_guest_name_rejected_400(book):
    resp = book(guest_name="   ")
    assert resp.status_code == 400


def test_booking_invalid_email_rejected_400(book):
    resp = book(guest_email="not-an-email")
    assert resp.status_code == 400


def test_booking_valid_guest_still_accepted(book):
    resp = book()
    assert resp.status_code == 200


def test_create_room_negative_price_rejected_400(client):
    payload = {
        "room_number": "999",
        "room_type": "double",
        "capacity": 2,
        "price_per_night": -500,
    }
    resp = client.post("/api/rooms/", json=payload)
    assert resp.status_code == 400
    assert "positivt" in resp.json()["detail"]


def test_create_room_zero_price_rejected_400(client):
    payload = {
        "room_number": "998",
        "room_type": "double",
        "capacity": 2,
        "price_per_night": 0,
    }
    assert client.post("/api/rooms/", json=payload).status_code == 400


def test_create_room_zero_capacity_rejected_400(client):
    payload = {
        "room_number": "997",
        "room_type": "double",
        "capacity": 0,
        "price_per_night": 1000,
    }
    assert client.post("/api/rooms/", json=payload).status_code == 400


def test_create_room_empty_room_number_rejected_400(client):
    payload = {
        "room_number": "",
        "room_type": "double",
        "capacity": 2,
        "price_per_night": 1000,
    }
    assert client.post("/api/rooms/", json=payload).status_code == 400


def test_create_room_valid_still_accepted(client):
    payload = {
        "room_number": "996",
        "room_type": "double",
        "capacity": 2,
        "price_per_night": 1000,
    }
    resp = client.post("/api/rooms/", json=payload)
    assert resp.status_code == 201
    assert resp.json()["room_number"] == "996"


# --- F7: falsy filter values must apply, not be skipped ----------------------

def test_list_bookings_room_id_zero_filters_not_returns_all(client, book):
    # F7: ?room_id=0 used to return ALL bookings (truthiness skipped filter).
    assert book(room_id=1).status_code == 200
    resp = client.get("/api/bookings/", params={"room_id": 0})
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_bookings_room_id_filter_matches(client, book):
    assert book(room_id=1).status_code == 200
    resp = client.get("/api/bookings/", params={"room_id": 1})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_bookings_status_filter_applies(client, book):
    created = book().json()
    client.put(
        f"/api/bookings/{created['id']}/cancel",
        headers={"X-Cancel-Token": created["cancel_token"]},
    )
    resp = client.get("/api/bookings/", params={"status": "confirmed"})
    assert resp.status_code == 200
    assert resp.json() == []
    resp = client.get("/api/bookings/", params={"status": "cancelled"})
    assert len(resp.json()) == 1
