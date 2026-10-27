from sqlalchemy import Column, Integer, String, Date, ForeignKey, Boolean
from app.database import Base


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    guest_name = Column(String(100), nullable=False)
    guest_email = Column(String(100), nullable=False)
    guest_phone = Column(String(20), default="")
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    check_in = Column(Date, nullable=False)
    check_out = Column(Date, nullable=False)
    total_price = Column(Integer, default=0)  # in SEK
    status = Column(String(20), default="confirmed")  # confirmed, cancelled, completed
    # Ownership proof for cancel (card 11535): random token generated at
    # booking time, returned exactly once in the booking-success response;
    # the cancel endpoint requires it back as X-Cancel-Token. NULL only on
    # rows that predate the fix (legacy demo rows).
    cancel_token = Column(String, nullable=True)

    def __repr__(self):
        return f"<Booking #{self.id} Room {self.room_id}>"
