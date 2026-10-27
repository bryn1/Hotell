import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.exc import OperationalError
from app.database import engine, SessionLocal, Base
from app.models.room import Room
from app.routers.rooms import router as rooms_router
from app.routers.bookings import router as bookings_router
from app.routers.calendar import router as calendar_router
from app.config import get_settings
from app.seed import seed_rooms

settings = get_settings()

# Ensure data directory exists — same path the DB_URL in app/config.py uses
# (MC 1290.2 / audit F1: was "data" while config points at ./.data/hotel.db,
# so a fresh clone crashed on boot with sqlite3.OperationalError).
os.makedirs(".data", exist_ok=True)

Base.metadata.create_all(bind=engine)

# Light forward-only migration (card 11535): create_all never alters an
# existing table, so an already-deployed bookings table has no cancel_token
# column. SQLite has no ADD COLUMN IF NOT EXISTS, so the ALTER is attempted
# and the OperationalError of an existing column is the expected no-op.
# Forward-only by design — there is no downgrade path.
try:
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "ALTER TABLE bookings ADD COLUMN cancel_token VARCHAR"
        )
except OperationalError:
    pass  # column already present (fresh create_all or a previous boot)

# Idempotently seed the four demo rooms so the site is shoppable on a fresh
# deploy / empty DB. Safe to run every boot: existing rooms are skipped.
seed_rooms(SessionLocal())

app = FastAPI(title=settings.APP_NAME, version="0.1.0")

# MC 2034.2 — public demo: per-visitor rate limit on mutating requests.
from app.demo_guard import DemoWriteGuard
app.add_middleware(DemoWriteGuard)

# Serve static files (CSS, JS, images)
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(rooms_router)
app.include_router(bookings_router)
app.include_router(calendar_router)


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}


@app.get("/")
def index():
    return FileResponse("templates/index.html")
