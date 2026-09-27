/**
 * render-calendar.js — Calendar Page (Room × Date Grid)
 *
 * Renders an intuitive booking matrix: one row per room, one column per date.
 * The first column is a frozen room label; each room×date cell shows whether
 * the room is available (Ledig) or booked (Bokad) on that night.
 *
 * Supports month navigation, room type filtering, and today highlighting.
 * Grid is wrapped in a horizontal-scroll container (.table-wrap) so a full
 * month stays usable on small screens.
 *
 * Depends on: utils/api.js (API_BASE, apiGet, Endpoints)
 */

/* global API_BASE, apiGet, Endpoints */
const calendarModule = (() => {
  // ---- State ----
  let currentYear = new Date().getFullYear();
  let currentMonth = new Date().getMonth() + 1; // 1-indexed
  let rooms = []; // Cached rooms list
  let roomsLoaded = false;

  // ---- Swedish month/day names ----
  const MONTH_NAMES = [
    'Januari', 'Februari', 'Mars', 'April', 'Maj', 'Juni',
    'Juli', 'Augusti', 'September', 'Oktober', 'November', 'December',
  ];

  const DAY_NAMES = ['Mån', 'Tis', 'Ons', 'Tor', 'Fre', 'Lör', 'Sön'];

  // Room type → display label (Swedish)
  const ROOM_TYPE_LABELS = {
    single: 'Enkel',
    double: 'Dubbel',
    four_person: 'Fyrasäng',
  };

  // Room type colors (from design spec)
  const ROOM_TYPE_COLORS = {
    single: { bg: '#e0f2fe', border: '#0369a1', text: '#075985' },   // primary-100/600/700
    double: { bg: '#d1fae5', border: '#047857', text: '#065f46' },   // accent-100/600/700
    four_person: { bg: '#fef3c7', border: '#d97706', text: '#92400e' }, // warning-100/warning/secondary-800
  };

  // ---- API ----
  // Returns null on fetch failure so the caller can fail CLOSED (show the
  // error/empty state) instead of rendering an all-available matrix.
  async function fetchCalendar(year, month) {
    try {
      const res = await apiGet(Endpoints.calendar(year, month));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.error('Failed to load calendar:', err);
      return null;
    }
  }

  async function fetchRooms() {
    if (roomsLoaded) return rooms;
    try {
      const res = await apiGet(Endpoints.rooms);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      rooms = await res.json();
      roomsLoaded = true;
    } catch (err) {
      console.error('Failed to load rooms:', err);
      rooms = [];
    }
    return rooms;
  }

  // ---- Date helpers ----
  function getDaysInMonth(year, month) {
    return new Date(year, month, 0).getDate();
  }

  function formatDate(year, month, day) {
    return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  }

  function isToday(year, month, day) {
    const now = new Date();
    return now.getFullYear() === year &&
          now.getMonth() + 1 === month &&
          now.getDate() === day;
  }

  function weekdayIndex(year, month, day) {
    // 0 = Monday … 6 = Sunday (DAY_NAMES order)
    const jsDay = new Date(year, month - 1, day).getDay(); // 0 = Sunday
    return jsDay === 0 ? 6 : jsDay - 1;
  }

  // ---- Pure layout: build room × date matrix ----
  //
  // Returns { days: [{date, dayNumber, weekday, isToday}], rooms: [{room,
  // statuses: [{date, available, booking_id}] }] } for the visible month only
  // (no prev/next padding — a date-column grid has no empty cells).
  function buildRoomDateMatrix(year, month, data, roomList) {
    const daysInMonth = getDaysInMonth(year, month);

    const days = [];
    for (let day = 1; day <= daysInMonth; day++) {
      days.push({
        date: formatDate(year, month, day),
        dayNumber: day,
        weekday: DAY_NAMES[weekdayIndex(year, month, day)],
        isToday: isToday(year, month, day),
      });
    }

    // Lookup: date -> { room_id: { available, booking_id } }
    const dayLookup = {};
    (data.days || []).forEach((dayEntry) => {
      dayLookup[dayEntry.date] = {};
      Object.entries(dayEntry).forEach(([key, val]) => {
        if (key.startsWith('room_')) {
          const roomId = parseInt(key.replace('room_', ''), 10);
          dayLookup[dayEntry.date][roomId] = val;
        }
      });
    });

    const roomsMatrix = roomList.map((room) => {
      const statuses = days.map((d) => {
        const dayData = dayLookup[d.date] || {};
        const cell = dayData[room.id];
        return {
          date: d.date,
          available: cell ? cell.available : true,
          booking_id: cell ? cell.booking_id : null,
        };
      });
      return { room, statuses };
    });

    return { days, rooms: roomsMatrix };
  }

  // ---- Rendering: Month Label ----
  function updateMonthLabel() {
    const label = document.getElementById('calendar-month-label');
    if (label) {
      label.textContent = `${MONTH_NAMES[currentMonth - 1]} ${currentYear}`;
    }
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ---- Rendering: Grid ----
  function renderCalendarGrid(year, month, data, container) {
    if (!container) container = document.getElementById('calendar-weeks');
    if (!container) return;

    // Get room type filter
    const roomTypeFilter = document.getElementById('filter-room-type');
    const selectedType = roomTypeFilter ? roomTypeFilter.value : '';

    // Filter rooms by type
    const filteredRooms = rooms.filter((r) => {
      if (!selectedType) return true;
      return r.room_type === selectedType;
    });

    if (filteredRooms.length === 0) {
      container.innerHTML = `
        <div class="calendar-empty" role="status">
          <div class="calendar-empty__icon" aria-hidden="true">📅</div>
          <p class="calendar-empty__message">Inga rum tillgängliga för valt filter.</p>
        </div>`;
      return;
    }

    const { days, rooms: roomsMatrix } = buildRoomDateMatrix(year, month, data, filteredRooms);

    // --- Header row: corner label + one column per date ---
    let html = '<div class="calendar-grid__header" role="row">';
    html += '<div class="calendar-grid__header-corner" role="columnheader" aria-label="Rum">Rum</div>';
    days.forEach((d) => {
      const todayCls = d.isToday ? ' is-today' : '';
      html +=
        `<div class="calendar-grid__header-cell${todayCls}" role="columnheader" aria-label="${d.date}">` +
          `<span class="calendar-grid__header-weekday">${d.weekday}</span>` +
          `<span class="calendar-grid__header-day">${d.dayNumber}</span>` +
        `</div>`;
    });
    html += '</div>';

    // --- Body: one row per room ---
    html += '<div class="calendar-grid__body" role="rowgroup">';

    roomsMatrix.forEach(({ room, statuses }) => {
      const color = ROOM_TYPE_COLORS[room.room_type] || ROOM_TYPE_COLORS.single;
      const typeLabel = ROOM_TYPE_LABELS[room.room_type] || '';
      const roomTitle = `Rum ${escapeHtml(room.room_number)}${typeLabel ? ` (${typeLabel})` : ''}`;

      html += `<div class="calendar-grid__row" role="row">`;
      html +=
        `<div class="calendar-grid__row-label" role="rowheader" style="--room-accent:${color.border}">` +
          `<span class="calendar-grid__row-room">${escapeHtml(room.room_number)}</span>` +
          `<span class="calendar-grid__row-type">${escapeHtml(typeLabel)}</span>` +
        `</div>`;

      statuses.forEach((cell) => {
        const stateCls = cell.available
          ? 'calendar-grid__cell--available'
          : 'calendar-grid__cell--booked';
        const title = cell.available
          ? `Rum ${escapeHtml(room.room_number)} ledigt ${cell.date}`
          : `Rum ${escapeHtml(room.room_number)} bokat ${cell.date}`;
        html +=
          `<div class="calendar-grid__cell ${stateCls}" role="gridcell" data-date="${cell.date}" aria-label="${title}" title="${title}">` +
            `<span class="sr-only">${cell.available ? 'Ledigt' : 'Bokat'}</span>` +
          `</div>`;
      });

      html += '</div>';
    });

    html += '</div>';
    container.innerHTML = html;
  }

  // ---- Rendering: Room Legend ----
  function renderRoomLegend(container) {
    if (!container) container = document.getElementById('calendar-room-legend');
    if (!container) return;

    const roomTypeFilter = document.getElementById('filter-room-type');
    const selectedType = roomTypeFilter ? roomTypeFilter.value : '';
    const filteredRooms = rooms.filter((r) => {
      if (!selectedType) return true;
      return r.room_type === selectedType;
    });

    if (filteredRooms.length === 0) {
      container.innerHTML = '<p class="calendar-empty__text">Inga rum tillgängliga.</p>';
      return;
    }

    container.innerHTML = filteredRooms.map((room) => {
      const color = ROOM_TYPE_COLORS[room.room_type] || ROOM_TYPE_COLORS.single;
      const typeLabel = ROOM_TYPE_LABELS[room.room_type] || room.room_type;
      return `<div class="calendar-legend__item" title="Rum ${escapeHtml(room.room_number)} (${escapeHtml(typeLabel)})">
        <span class="calendar-legend__dot" style="background:${color.border}" aria-hidden="true"></span>
        <span class="calendar-legend__label">Rum ${escapeHtml(room.room_number)}</span>
      </div>`;
    }).join('');
  }

  // ---- Month Navigation ----
  function navigateMonth(direction) {
    currentMonth += direction;
    if (currentMonth > 12) {
      currentMonth = 1;
      currentYear++;
    } else if (currentMonth < 1) {
      currentMonth = 12;
      currentYear--;
    }
    loadCalendar();
  }

  function goToday() {
    const now = new Date();
    currentYear = now.getFullYear();
    currentMonth = now.getMonth() + 1;
    loadCalendar();
  }

  // ---- Load & Render ----
  async function loadCalendar() {
    await fetchRooms();
    const data = await fetchCalendar(currentYear, currentMonth);
    updateMonthLabel();
    if (data === null) {
      // Fail closed: fetch error must NOT render an all-available matrix.
      renderCalendarError();
      renderRoomLegend();
      return;
    }
    renderCalendarGrid(currentYear, currentMonth, data);
    renderRoomLegend();
  }

  // ---- Rendering: Error State ----
  function renderCalendarError() {
    const container = document.getElementById('calendar-weeks');
    if (!container) return;
    container.innerHTML = `
      <div class="calendar-empty" role="alert">
        <div class="calendar-empty__icon" aria-hidden="true">📅</div>
        <p class="calendar-empty__message">Kunde inte läsa in kalendern. Försök igen.</p>
      </div>`;
  }

  // ---- Public API ----
  function getCurrentYear() { return currentYear; }
  function getCurrentMonth() { return currentMonth; }
  function getDaysInMonthPublic(y, m) { return getDaysInMonth(y, m); }

  // ---- Initialization ----
  function init() {
    // Month navigation
    const prevBtn = document.getElementById('cal-prev-month');
    const nextBtn = document.getElementById('cal-next-month');
    const todayBtn = document.getElementById('cal-today');

    if (prevBtn) prevBtn.addEventListener('click', () => navigateMonth(-1));
    if (nextBtn) nextBtn.addEventListener('click', () => navigateMonth(1));
    if (todayBtn) todayBtn.addEventListener('click', goToday);

    // Room type filter
    const roomTypeFilter = document.getElementById('filter-room-type');
    if (roomTypeFilter) roomTypeFilter.addEventListener('change', () => loadCalendar());

    // Initial data (whitespace in this element is stripped; safe to re-render)
    const wrapper = document.getElementById('calendar-weeks');
    if (wrapper) wrapper.setAttribute('aria-busy', 'true');

    loadCalendar().finally(() => {
      if (wrapper) wrapper.setAttribute('aria-busy', 'false');
    });
  }

  return {
    init,
    loadCalendar,
    navigateMonth,
    goToday,
    getCurrentYear,
    getCurrentMonth,
    buildRoomDateMatrix,
    getDaysInMonth: getDaysInMonthPublic,
  };
})();
