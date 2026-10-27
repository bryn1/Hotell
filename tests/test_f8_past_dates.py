"""Regression tests for MC 1310.1 audit fixes: F8 (past check-in dates).

F8 (LOW, audit 1290.1): the API accepted bookings with a check-in date in the
past (e.g. 2020 -> 200 confirmed). The frontend blocks this, but the API must
enforce it server-side: check_in >= today (local date) and check_out >
check_in, rejected with 422 and a clear Swedish error message. Tests use the shared `book`
fixture from conftest.py (MC 11534).
"""
from datetime import date, timedelta


def _today() -> date:
    return date.today()


# --- F8: past check-in must be rejected with 422 -----------------------------

def test_past_check_in_rejected_422(book):
    resp = book(check_in="2020-01-01", check_out="2020-01-03")
    assert resp.status_code == 422
    assert "förfluten" in resp.json()["detail"] or "framtid" in resp.json()["detail"]


def test_yesterday_check_in_rejected_422(book):
    yesterday = (_today() - timedelta(days=1)).isoformat()
    day_after = (_today() + timedelta(days=1)).isoformat()
    resp = book(check_in=yesterday, check_out=day_after)
    assert resp.status_code == 422


def test_today_check_in_accepted(book):
    # Boundary: check_in == today is allowed (check-in day itself is bookable).
    today = _today().isoformat()
    tomorrow = (_today() + timedelta(days=2)).isoformat()
    resp = book(check_in=today, check_out=tomorrow)
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"


def test_future_check_in_still_accepted(book):
    resp = book(check_in="2099-01-01", check_out="2099-01-03")
    assert resp.status_code == 200
    assert resp.json()["total_price"] == 2400


def test_check_out_equal_to_today_with_past_check_in_rejected_422(book):
    # check_out in the past too — the check_in rule fires first.
    resp = book(check_in="2020-01-01", check_out="2020-01-02")
    assert resp.status_code == 422
