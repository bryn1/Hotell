/**
 * render-bookings.js — Bookings Management Page
 *
 * Provides a data table for viewing, filtering, sorting, and cancelling
 * hotel bookings. Follows BEM naming and uses design-system.css tokens.
 */

const bookingsModule = (() => {
  // ---- State ----
  let allBookings = [];
  let currentSort = { key: 'date', dir: 'desc' };
  let currentFilters = { status: '', dateFrom: '', dateTo: '', room: '' };

  // ---- Swedish labels for statuses ----
  const STATUS_LABELS = {
    confirmed: 'Bekräftad',
    cancelled: 'Avbruten',
    completed: 'Slutförd',
  };

  // ---- XSS guard (audit F2, MC 1290.2) ----
  // Same escapeHtml pattern as render-rooms.js: API-stored strings (guest
  // name/email) are user-controlled and MUST be escaped at render time.
  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
  }

  // ---- API ----
  async function fetchBookings() {
    try {
      const res = await apiGet(Endpoints.bookings);
      return await res.json();
    } catch (err) {
      console.error('Failed to load bookings:', err);
      return [];
    }
  }

  async function cancelBooking(id) {
    try {
      const res = await fetch(API_BASE + Endpoints.cancel(id), { method: 'PUT' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.error('Failed to cancel booking:', err);
      throw err;
    }
  }

  // ---- Data helpers ----
  function formatCheckIn(dateStr) {
    if (!dateStr) return '—';
    const d = new Date(dateStr);
    return d.toLocaleDateString('sv-SE', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function formatCheckOut(dateStr) {
    if (!dateStr) return '—';
    const d = new Date(dateStr);
    return d.toLocaleDateString('sv-SE', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function formatDate(dateStr) {
    if (!dateStr) return '—';
    return dateStr;
  }

  function formatPrice(price) {
    if (price == null) return '—';
    return `${price.toLocaleString('sv-SE')} kr`;
  }

  // ---- Filtering ----
  function filterBookings(bookings, filters) {
    return bookings.filter(b => {
      if (filters.status && b.status !== filters.status) return false;
      if (filters.dateFrom && b.check_in < filters.dateFrom) return false;
      if (filters.dateTo && b.check_in > filters.dateTo) return false;
      if (filters.room && String(b.room_id) !== String(filters.room)) return false;
      return true;
    });
  }

  // ---- Sorting ----
  function sortBookings(bookings, { key, dir }) {
    const sorted = [...bookings].sort((a, b) => {
      let aVal, bVal;
      switch (key) {
        case 'id':
          aVal = a.id; bVal = b.id; break;
        case 'guest':
          aVal = a.guest_name; bVal = b.guest_name; break;
        case 'room':
          aVal = a.room_id; bVal = b.room_id; break;
        case 'dates':
        case 'date':
          aVal = a.check_in; bVal = b.check_in; break;
        case 'price':
          aVal = a.total_price; bVal = b.total_price; break;
        case 'status':
          aVal = a.status; bVal = b.status; break;
        default:
          aVal = a.check_in; bVal = b.check_in;
      }
      if (aVal < bVal) return dir === 'asc' ? -1 : 1;
      if (aVal > bVal) return dir === 'asc' ? 1 : -1;
      return 0;
    });
    return sorted;
  }

  // ---- Rendering: Status Badge ----
  function renderStatusBadge(status) {
    const label = STATUS_LABELS[status] || status;
    return `<span class="status-badge status-badge--${status}">
      <span class="status-badge__dot" aria-hidden="true"></span>
      ${label}
    </span>`;
  }

  // ---- Rendering: Single Row ----
  function renderBookingRow(booking) {
    // Audit F2: guest_name is user-controlled — escape before it touches
    // innerHTML (both the title attribute and the cell text).
    const rawName = String(booking.guest_name || '');
    const guest = rawName.length > 25
      ? escapeHtml(rawName.slice(0, 25)) + '…'
      : escapeHtml(rawName);
    const guestTitle = escapeHtml(rawName);

    return `<tr data-booking-id="${booking.id}">
      <td>#${booking.id}</td>
      <td title="${guestTitle}">${guest}</td>
      <td>Rum ${escapeHtml(booking.room_number || booking.room_id)}</td>
      <td>
        <div class="date-range">
          <span class="date-range__checkin">${formatCheckIn(booking.check_in)}</span>
          <span class="date-range__arrow" aria-hidden="true">→</span>
          <span class="date-range__checkout">${formatCheckOut(booking.check_out)}</span>
        </div>
      </td>
      <td>${formatPrice(booking.total_price)}</td>
      <td>${renderStatusBadge(booking.status)}</td>
      <td>
        ${booking.status === 'confirmed'
          ? `<button type="button" class="btn btn-danger btn-sm bookings-action--cancel" data-booking-id="${booking.id}" aria-label="Avbryt bokning #${booking.id}">Avbryt</button>`
          : '—'}
      </td>
    </tr>`;
  }

  // ---- Rendering: Table ----
  function renderBookingsTable(bookings, container) {
    if (!container) container = document.getElementById('bookings-tbody');
    if (!container) return;

    const emptyEl = document.getElementById('bookings-empty');
    const loadingEl = document.getElementById('bookings-loading');

    if (bookings.length === 0) {
      container.innerHTML = '';
      if (emptyEl) emptyEl.hidden = false;
      if (loadingEl) loadingEl.hidden = true;
      return;
    }

    if (emptyEl) emptyEl.hidden = true;
    if (loadingEl) loadingEl.hidden = true;

    container.innerHTML = bookings.map(b => renderBookingRow(b)).join('');

    // Wire up cancel buttons
    container.querySelectorAll('.bookings-action--cancel').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = parseInt(btn.dataset.bookingId, 10);
        showCancelConfirm(id);
      });
    });
  }

  // ---- Rendering: Update count ----
  function updateCount(total, filtered) {
    const countEl = document.getElementById('booking-count');
    if (countEl) {
      // Swedish pluralization: "1 bokning" / "N bokningar"
      const noun = total === 1 ? 'bokning' : 'bokningar';
      if (filtered !== total) {
        countEl.textContent = `Visar ${filtered} av ${total} ${noun}`;
      } else {
        countEl.textContent = `${total} ${noun}`;
      }
    }
  }

  // ---- Cancel Confirmation Dialog ----
  function showCancelConfirm(bookingId) {
    const dialog = document.getElementById('cancel-confirm-dialog');
    const detailEl = document.getElementById('cancel-detail');
    const confirmBtn = document.getElementById('confirm-cancel-btn');
    const cancelBtn = document.getElementById('cancel-dialog-btn');

    if (!dialog || !detailEl) return;

    const booking = allBookings.find(b => b.id === bookingId);
    if (!booking) return;

    // Audit F2: textContent assignment (not innerHTML) — no escaping needed
    // here, but keep the truncation consistent with the table row.
    const guestName = booking.guest_name.length > 25
      ? booking.guest_name.slice(0, 25) + '…'
      : booking.guest_name;

    detailEl.textContent = `Vill du verkligen avbryta bokning #${bookingId} (${guestName}, Rum ${booking.room_number || booking.room_id}, ${formatCheckIn(booking.check_in)} – ${formatCheckOut(booking.check_out)})?`;

    // Remove old listeners by cloning
    if (confirmBtn) {
      const newBtn = confirmBtn.cloneNode(true);
      confirmBtn.parentNode.replaceChild(newBtn, confirmBtn);
      newBtn.addEventListener('click', async () => {
        try {
          await cancelBooking(bookingId);
          dialog.close();
          await loadBookings();
          showToast('Bokning avbruten', 'success');
        } catch (err) {
          showToast('Kunde inte avbryta bokning', 'error');
        }
      });
    }

    if (cancelBtn) {
      const newBtn = cancelBtn.cloneNode(true);
      cancelBtn.parentNode.replaceChild(newBtn, cancelBtn);
      newBtn.addEventListener('click', () => dialog.close());
    }

    if (dialog.showModal) {
      dialog.showModal();
    }
  }

  // ---- Toast Notification ----
  function showToast(message, type = 'info') {
    // Use global toast system if available, otherwise console
    if (typeof showToastGlobal === 'function') {
      showToastGlobal(message, type);
    } else {
      console.log(`[${type}] ${message}`);
    }
  }

  // ---- Public API ----
  async function loadBookings() {
    renderSkeletonLoading();
    allBookings = await fetchBookings();
    applyFiltersAndSort();
  }

  function applyFiltersAndSort() {
    let result = filterBookings(allBookings, currentFilters);
    result = sortBookings(result, currentSort);
    renderBookingsTable(result);
    updateCount(allBookings.length, result.length);
    updateSortIndicators();
  }

  function updateSortIndicators() {
    const ths = document.querySelectorAll('#bookings-table th.sortable');
    ths.forEach(th => {
      const key = th.dataset.sortKey;
      th.classList.remove('sort-asc', 'sort-desc');
      if (key === currentSort.key) {
        th.classList.add(currentSort.dir === 'asc' ? 'sort-asc' : 'sort-desc');
        th.setAttribute('aria-sort', currentSort.dir === 'asc' ? 'ascending' : 'descending');
      } else {
        th.setAttribute('aria-sort', 'none');
      }
    });
  }

  function setSort(key) {
    if (currentSort.key === key) {
      currentSort.dir = currentSort.dir === 'asc' ? 'desc' : 'asc';
    } else {
      currentSort.key = key;
      currentSort.dir = key === 'guest' ? 'asc' : 'desc';
    }
    applyFiltersAndSort();
  }

  function setFilters(filters) {
    currentFilters = { ...currentFilters, ...filters };
    applyFiltersAndSort();
  }

  function clearFilters() {
    currentFilters = { status: '', dateFrom: '', dateTo: '', room: '' };
    // Reset select inputs
    const statusSelect = document.getElementById('filter-status');
    if (statusSelect) statusSelect.value = '';
    const dateFromInput = document.getElementById('filter-date-from');
    if (dateFromInput) dateFromInput.value = '';
    const dateToInput = document.getElementById('filter-date-to');
    if (dateToInput) dateToInput.value = '';
    applyFiltersAndSort();
  }

  function getBookings() {
    return allBookings;
  }

  // ---- Initialization ----
  function init() {
    // Sortable columns
    document.querySelectorAll('#bookings-table th.sortable').forEach(th => {
      th.addEventListener('click', () => {
        setSort(th.dataset.sortKey);
      });
      th.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          setSort(th.dataset.sortKey);
        }
      });
    });

    // Filter: status
    const statusSelect = document.getElementById('filter-status');
    if (statusSelect) {
      statusSelect.addEventListener('change', () => {
        setFilters({ status: statusSelect.value });
      });
    }

    // Filter: date range
    const dateFrom = document.getElementById('filter-date-from');
    if (dateFrom) {
      dateFrom.addEventListener('change', () => {
        setFilters({ dateFrom: dateFrom.value });
      });
    }
    const dateTo = document.getElementById('filter-date-to');
    if (dateTo) {
      dateTo.addEventListener('change', () => {
        setFilters({ dateTo: dateTo.value });
      });
    }

    // Clear filters button
    const clearBtn = document.getElementById('clear-bookings-filter');
    if (clearBtn) {
      clearBtn.addEventListener('click', clearFilters);
    }

    // Load initial data
    loadBookings();
  }

  return {
    init,
    loadBookings,
    setSort,
    setFilters,
    clearFilters,
    filterBookings,
    sortBookings,
    renderBookingsTable,
    renderBookingRow,
    cancelBooking,
    getBookings,
  };
})();
