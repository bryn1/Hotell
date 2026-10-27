from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models.room import Room
from app.models.booking import Booking
from pydantic import BaseModel
from datetime import date, datetime
import re
import secrets

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


class RoomCreate(BaseModel):
    room_number: str
    room_type: str
    capacity: int
    price_per_night: int
    sea_view: bool = True
    description: str = ""


# Audit F5 (MC 1290.2): simple server-side validation, PoC scope.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _validate_guest(name: str, email: str) -> None:
    if not name or not name.strip():
        raise HTTPException(400, "Gästnamn får inte vara tomt")
    if not email or not _EMAIL_RE.match(email.strip()):
        raise HTTPException(400, "Ogiltig e-postadress")


class RoomOut(BaseModel):
    id: int
    room_number: str
    room_type: str
    capacity: int
    price_per_night: int
    sea_view: bool
    description: str

    class Config:
        from_attributes = True


class BookingRequest(BaseModel):
    guest_name: str
    guest_email: str
    guest_phone: str = ""
    check_in: str  # YYYY-MM-DD
    check_out: str  # YYYY-MM-DD


class BookingOut(BaseModel):
    id: int
    guest_name: str
    room_id: int
    check_in: str
    check_out: str
    total_price: int
    status: str
    cancel_token: Optional[str] = None


def _booking_to_dict(booking: Booking) -> dict:
    ci = booking.check_in.isoformat() if isinstance(booking.check_in, date) else booking.check_in
    co = booking.check_out.isoformat() if isinstance(booking.check_out, date) else booking.check_out
    # Read-minimization (card 11535): no PII in responses — guest_email/
    # guest_phone are stored but never returned. cancel_token is returned
    # exactly once, here in the booking-success response, as the ownership
    # proof the cancel endpoint later requires (X-Cancel-Token).
    return {
        "id": booking.id,
        "guest_name": booking.guest_name,
        "room_id": booking.room_id,
        "check_in": ci,
        "check_out": co,
        "total_price": booking.total_price,
        "status": booking.status,
        "cancel_token": booking.cancel_token,
    }


@router.get("/", response_model=List[RoomOut])
def list_rooms(db: Session = Depends(get_db), sea_view_only: bool = False):
    q = db.query(Room)
    if sea_view_only:
        q = q.filter(Room.sea_view == True)
    return q.all()


@router.post("/", status_code=201)
def create_room(room: RoomCreate, db: Session = Depends(get_db)):
    # Audit F5: reject empty room_number, non-positive price, capacity < 1.
    if not room.room_number or not room.room_number.strip():
        raise HTTPException(400, "Rumnummer får inte vara tomt")
    if room.price_per_night <= 0:
        raise HTTPException(400, "Pris per natt måste vara positivt")
    if room.capacity < 1:
        raise HTTPException(400, "Kapacitet måste vara minst 1")
    existing = db.query(Room).filter(Room.room_number == room.room_number).first()
    if existing:
        raise HTTPException(400, f"Room {room.room_number} already exists")
    db_room = Room(**room.model_dump())
    db.add(db_room)
    db.commit()
    db.refresh(db_room)
    return db_room


@router.get("/{room_id}/", response_model=RoomOut)
def get_room(room_id: int, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(404, "Room not found")
    return room


@router.post("/{room_id}/book", response_model=BookingOut)
def book_room(room_id: int, booking: BookingRequest, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(404, "Room not found")

    # Audit F5: server-side guest validation (frontend checks are not enough).
    _validate_guest(booking.guest_name, booking.guest_email)

    try:
        ci = datetime.strptime(booking.check_in, "%Y-%m-%d").date()
        co = datetime.strptime(booking.check_out, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "Ogiltigt datumformat, använd YYYY-MM-DD")

    # Audit F8 (MC 1310.1): server-side past-date validation. The frontend
    # blocks past dates, but the API must not trust that — reject check-ins
    # before today (local date) with 422.
    if ci < date.today():
        raise HTTPException(422, "Incheckningsdatum kan inte ligga i förfluten tid")

    if co <= ci:
        raise HTTPException(400, "Utcheckning måste vara efter incheckning")

    overlaps = db.query(Booking).filter(
        Booking.room_id == room_id,
        Booking.status == "confirmed",
        Booking.check_out > ci,
        Booking.check_in < co
    ).first()

    if overlaps:
        raise HTTPException(400, "Room not available for these dates")

    nights = (co - ci).days
    total = nights * room.price_per_night

    db_booking = Booking(
        guest_name=booking.guest_name,
        guest_email=booking.guest_email,
        guest_phone=booking.guest_phone,
        room_id=room_id,
        check_in=ci,
        check_out=co,
        total_price=total,
        # Ownership proof for cancel (card 11535); handed to the caller once
        # in the success response and required back as X-Cancel-Token.
        cancel_token=secrets.token_urlsafe(16),
    )
    db.add(db_booking)
    db.commit()
    db.refresh(db_booking)
    return _booking_to_dict(db_booking)
