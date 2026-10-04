# Hotell — Sea View Hotel bokningssystem

Komplett webbaserad bokningssida för hotellrum. FastAPI + SQLite backend, vanlig HTML/CSS/JS frontend med design system och HTMX-fritt men fullt interaktivt bokningsflöde.

## Funktioner
- Visa alla rum som kort, med filter (typ, kapacitet, pris) och sortering
- Rumdetaljvy (modal) och rumstyp-amenities
- Boka ett rum: välj datumintervall → prissumma uppdateras live → bekräftelse
- Visa, filtrera, sortera och avboka bokningar
- Bokningskalender per månad med per-rum tillgänglighet
- Dark mode-toggle, toast-notiser, tangentbordsnavigering, responsiv design
- Konflikt-detektering: dubbelbokning av samma rum/datum blockeras

## Teknikstack
- **Backend**: FastAPI + SQLAlchemy + SQLite (aiosqlite)
- **Frontend**: Vanilla JS (rooms, bookings, calendar, booking-flow) + design-system CSS
- **Konfig**: pydantic-settings (`.env`)

## Snabbstart (lokal utveckling)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Port 8000 är taget av annan tjänst på denna host — använd t.ex. 8500
uvicorn app.main:app --host 0.0.0.0 --port 8500 --reload

# Öppna http://localhost:8500
```

## API Endpoints

| Metod | Sökväg | Beskrivning |
|---|---|---|
| GET | `/` | Bokningssidan (index.html) |
| GET | `/health` | Health check (`{"status":"ok","app":"Sea View Hotel"}`) |
| GET | `/api/rooms/` | Lista alla rum |
| POST | `/api/rooms/` | Skapa rum (admin) |
| POST | `/api/rooms/{id}/book` | Boka rum (kropp: guest_name, guest_email, guest_phone, check_in, check_out) |
| GET | `/api/bookings/` | Lista bokningar (filter: status, room_id) |
| GET | `/api/bookings/{booking_id}` | Visa en bokning |
| PUT | `/api/bookings/{booking_id}/cancel` | Avboka |
| GET | `/api/calendar/{year}/{month}` | Kalenderdata per månad |

## Deploy (vm106, git-medierad)

Gunilla-appen (`hotell`) är registrerad i `github.com/bryn1/hosting` `apps.yaml`
(`type: service`, port `8117`, exec `server.py`). Push till hosting-repos main:
vm106:s pull-timer renderar systemd-unit `vm106-app-hotell.service` + nginx-location
`/hotell/` → proxy till `127.0.0.1:8117`. Se `apps/hotell/` för den deployade kopian.

## Demo-data
Vid start seedas 4 rum idempotent (`app/seed.py`): 101/102 dubbel, 201 enkel, 301 fyrbädds
— alla med havsutsikt. Inga bokningar är förseedade; databasen (`.data/hotel.db`) börjar tom
på bokningar och fylls när du bokar i demon.

## Hosting-entrypoint
`server.py` är produktionsentrypointen för vm106-hostingen: den binder `0.0.0.0:$PORT`
(default 8117, se `hosting.yaml`) och kör `app.main:app` utan reload. `run.py` (port 8000,
reload) är endast för lokal utveckling.
