from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models.booking import Booking
from app.models.room import Room
from pydantic import BaseModel
from datetime import date, datetime

router = APIRouter(prefix="/api/bookings", tags=["bookings"])


class BookingOut(BaseModel):
    id: int
    guest_name: str
    guest_email: str
    room_id: int
    room_number: Optional[str] = None
    check_in: str
    check_out: str
    total_price: int
    status: str


class BookingCreate(BaseModel):
    guest_name: str
    guest_email: str
    check_in: str
    check_out: str
    rooms: List[int]


def _to_dict(booking: Booking, room_number: Optional[str] = None) -> dict:
    return {
        "id": booking.id,
        "guest_name": booking.guest_name,
        "guest_email": booking.guest_email,
        "room_id": booking.room_id,
        "room_number": room_number,
        "check_in": booking.check_in.isoformat() if isinstance(booking.check_in, date) else booking.check_in,
        "check_out": booking.check_out.isoformat() if isinstance(booking.check_out, date) else booking.check_out,
        "total_price": booking.total_price,
        "status": booking.status,
    }


@router.get("/", response_model=List[BookingOut])
def list_bookings(
    status: Optional[str] = Query(None),
    room_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Booking)
    # Audit F7: use `is not None`, not truthiness — room_id=0 and status=""
    # are valid filter values and must not be skipped.
    if status is not None:
        q = q.filter(Booking.status == status)
    if room_id is not None:
        q = q.filter(Booking.room_id == room_id)
    # Join rooms once server-side so the list carries the human room number
    # (avoids a frontend N+1 fetch). room_id stays in the payload for
    # backward compatibility.
    room_numbers = dict(db.query(Room.id, Room.room_number).all())
    return [
        _to_dict(b, room_numbers.get(b.room_id))
        for b in q.order_by(Booking.check_in.desc()).all()
    ]


@router.get("/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: int, db: Session = Depends(get_db)):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(404, "Booking not found")
    return _to_dict(booking)


@router.put("/{booking_id}/cancel")
def cancel_booking(booking_id: int, db: Session = Depends(get_db)):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(404, "Booking not found")
    # State guard: cancelling is only valid from `confirmed`. Re-cancelling a
    # cancelled booking or cancelling a completed booking is a conflict.
    if booking.status == "cancelled":
        raise HTTPException(409, "Booking is already cancelled")
    if booking.status == "completed":
        raise HTTPException(409, "Completed bookings cannot be cancelled")
    booking.status = "cancelled"
    db.commit()
    return {"status": "cancelled"}
