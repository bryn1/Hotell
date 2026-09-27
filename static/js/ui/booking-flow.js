/**
 * booking-flow.js — Booking Flow Modal
 *
 * Handles the booking dialog: opening a form for a given room,
 * validating inputs, submitting to the API, and showing success/error
 * states. Follows BEM naming and uses design-system.css tokens.
 */

/* global API */
const bookingFlowModule = (() => {
  // ---- State ----
  let currentRoom = null;
  let isSubmitting = false;

  // ---- XSS guard (audit F2, MC 1290.2) ----
  // Same escapeHtml pattern as render-rooms.js: API-stored strings (guest
  // name/email) are user-controlled and MUST be escaped at render time.
  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
  }

  // ---- Swedish error messages ----
  const ERR_MESSAGES = {
    missingRoom: 'Välj ett rum.',
    missingGuestName: 'Ange ditt namn.',
    missingGuestEmail: 'Ange din e-postadress.',
    invalidEmail: 'Ogiltig e-postadress.',
    missingCheckIn: 'Välj incheckningsdatum.',
    missingCheckOut: 'Välj utcheckningsdatum.',
    checkOutBeforeCheckIn: 'Utcheckning måste vara efter incheckning.',
    checkInToday: 'Incheckning kan inte ligga i det förflutna.',
    minNights: 'Minsta bokningslängd är 1 natt.',
    apiError: 'Kunde inte skicka bokning. Försök igen.',
    alreadyBooked: 'Rummet är bokat för valda datum.',
    serverError: 'Serverfel. Försök igen senare.',
  };

  // ---- API ----
  async function submitBooking(roomId, data) {
    try {
      const res = await fetch(`${API}/api/rooms/${roomId}/book`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || ERR_MESSAGES.apiError);
      }
      return await res.json();
    } catch (err) {
      console.error('Booking submission failed:', err);
      throw err;
    }
  }

  // ---- Validation ----
  function validateForm(data) {
    const errors = [];

    // Guest name
    if (!data.guest_name || data.guest_name.trim().length === 0) {
      errors.push({ field: 'guest_name', message: ERR_MESSAGES.missingGuestName });
    } else if (data.guest_name.trim().length < 2) {
      errors.push({ field: 'guest_name', message: 'Namnet måste vara minst 2 tecken.' });
    }

    // Guest email
    if (!data.guest_email || data.guest_email.trim().length === 0) {
      errors.push({ field: 'guest_email', message: ERR_MESSAGES.missingGuestEmail });
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.guest_email.trim())) {
      errors.push({ field: 'guest_email', message: ERR_MESSAGES.invalidEmail });
    }

    // Check-in date
    if (!data.check_in || data.check_in.length === 0) {
      errors.push({ field: 'check_in', message: ERR_MESSAGES.missingCheckIn });
    } else {
      const checkInDate = new Date(data.check_in);
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      if (checkInDate < today) {
        errors.push({ field: 'check_in', message: ERR_MESSAGES.checkInToday });
      }
    }

    // Check-out date
    if (!data.check_out || data.check_out.length === 0) {
      errors.push({ field: 'check_out', message: ERR_MESSAGES.missingCheckOut });
    } else if (data.check_out.length > 0) {
      const checkOutDate = new Date(data.check_out);
      const checkInDate = data.check_in ? new Date(data.check_in) : null;

      if (checkInDate) {
        if (checkOutDate <= checkInDate) {
          errors.push({ field: 'check_out', message: ERR_MESSAGES.checkOutBeforeCheckIn });
        }
      }

      // Check minimum nights
      if (checkInDate && checkOutDate) {
        const diffDays = Math.ceil((checkOutDate - checkInDate) / (1000 * 60 * 60 * 24));
        if (diffDays < 1) {
          errors.push({ field: 'check_out', message: ERR_MESSAGES.minNights });
        }
      }
    }

    return errors;
  }

  // ---- Format dates for display ----
  function formatDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return d.toLocaleDateString('sv-SE', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    });
  }

  function formatDateShort(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return d.toLocaleDateString('sv-SE', {
      day: 'numeric',
      month: 'short',
    });
  }

  // ---- Render booking form ----
  function renderBookingForm(container, room) {
    if (!container || !room) return;

    const roomTypeLabel = {
      single: 'Enkel',
      double: 'Dubbel',
      four_person: 'Fyrasäng',
    }[room.room_type] || room.room_type;

    container.innerHTML = `
      <div class="booking-form__header">
        <h3 class="booking-form__title">Boka Rum ${escapeHtml(room.room_number)}</h3>
        <p class="booking-form__subtitle">${roomTypeLabel} — ${formatPrice(room.price_per_night)} kr/natt</p>
      </div>

      <form id="booking-flow-form" novalidate>
        <input type="hidden" id="booking-room-id" name="room_id" value="${room.id}">
        <div class="booking-form__fields">
          <div class="form-group booking-form__field-group">
            <label for="bf-guest-name" class="form-label">Namn *</label>
            <input
              type="text"
              id="bf-guest-name"
              name="guest_name"
              class="form-input"
              placeholder="Ditt namn"
              required
              autocomplete="name"
              minlength="2"
            >
            <span class="form-error" id="bf-guest-name-error" role="alert" aria-live="polite"></span>
          </div>

          <div class="form-group booking-form__field-group">
            <label for="bf-guest-email" class="form-label">E-post *</label>
            <input
              type="email"
              id="bf-guest-email"
              name="guest_email"
              class="form-input"
              placeholder="din@epost.se"
              required
              autocomplete="email"
            >
            <span class="form-error" id="bf-guest-email-error" role="alert" aria-live="polite"></span>
          </div>

          <div class="form-group booking-form__field-group">
            <label for="bf-guest-phone" class="form-label">Telefon</label>
            <input
              type="tel"
              id="bf-guest-phone"
              name="guest_phone"
              class="form-input"
              placeholder="+46 7X XXX XX XX"
              autocomplete="tel"
            >
          </div>

          <div class="form-group booking-form__field-group">
            <label for="bf-check-in" class="form-label">Incheckning *</label>
            <input
              type="date"
              id="bf-check-in"
              name="check_in"
              class="form-input"
              required
              min="${new Date().toISOString().split('T')[0]}"
            >
            <span class="form-error" id="bf-check-in-error" role="alert" aria-live="polite"></span>
          </div>

          <div class="form-group booking-form__field-group">
            <label for="bf-check-out" class="form-label">Utcheckning *</label>
            <input
              type="date"
              id="bf-check-out"
              name="check_out"
              class="form-input"
              required
              min="${new Date().toISOString().split('T')[0]}"
            >
            <span class="form-error" id="bf-check-out-error" role="alert" aria-live="polite"></span>
          </div>
        </div>

        <div class="booking-form__actions">
          <button type="submit" class="btn btn-primary btn-lg booking-form__submit" id="booking-submit-btn">
            Bekräfta bokning
          </button>
          <button type="button" class="btn btn-secondary btn-lg" id="booking-cancel-btn">
            Avbryt
          </button>
        </div>
      </form>
    `;

    // Wire up cancel button
    const cancelBtn = document.getElementById('booking-cancel-btn');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', closeModal);
    }

    // Wire up form submission
    const form = document.getElementById('booking-flow-form');
    if (form) {
      form.addEventListener('submit', handleSubmit);
    }

    // Set minimum check-out = check-in + 1 day
    const checkInInput = document.getElementById('bf-check-in');
    const checkOutInput = document.getElementById('bf-check-out');
    if (checkInInput && checkOutInput) {
      checkInInput.addEventListener('change', () => {
        if (checkInInput.value) {
          const nextDay = new Date(checkInInput.value);
          nextDay.setDate(nextDay.getDate() + 1);
          checkOutInput.min = nextDay.toISOString().split('T')[0];
          // If check-out is before new check-in + 1 day, reset it
          if (checkOutInput.value && new Date(checkOutInput.value) <= new Date(checkInInput.value)) {
            checkOutInput.value = '';
          }
        }
      });
    }
  }

  function formatPrice(price) {
    if (price == null) return '—';
    return price.toLocaleString('sv-SE');
  }

  // ---- Submit handler ----
  async function handleSubmit(e) {
    e.preventDefault();
    if (isSubmitting) return;

    const form = e.target;
    const data = {
      guest_name: form.guest_name.value.trim(),
      guest_email: form.guest_email.value.trim(),
      guest_phone: form.guest_phone.value.trim(),
      check_in: form.check_in.value,
      check_out: form.check_out.value,
    };

    // Validate
    const errors = validateForm(data);
    if (errors.length > 0) {
      displayErrors(errors);
      return;
    }

    // Clear errors
    clearErrors();

    // Submit
    isSubmitting = true;
    const submitBtn = document.getElementById('booking-submit-btn');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = `<span class="btn__spinner" aria-hidden="true">⏳</span> Skickar...`;
    }

    try {
      const booking = await submitBooking(currentRoom.id, data);
      const roomNumber = currentRoom ? currentRoom.room_number : null;
      closeModal();
      showSuccess(booking, roomNumber);
      // Refresh bookings table if it's open
      if (typeof bookingsModule !== 'undefined' && bookingsModule.loadBookings) {
        bookingsModule.loadBookings();
      }
    } catch (err) {
      showError(err.message || ERR_MESSAGES.serverError);
    } finally {
      isSubmitting = false;
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = 'Bekräfta bokning';
      }
    }
  }

  // ---- Error display ----
  function displayErrors(errors) {
    // Show inline field errors
    errors.forEach(err => {
      const errorEl = document.getElementById(`bf-${err.field}-error`);
      if (errorEl) {
        errorEl.textContent = err.message;
        errorEl.hidden = false;
      }
      // Highlight the field
      const input = document.getElementById(`bf-${err.field}`);
      if (input) {
        input.classList.add('invalid');
        input.setAttribute('aria-invalid', 'true');
      }
    });

    // Show summary toast if there are errors
    const firstError = errors[0];
    if (firstError && typeof showToastGlobal === 'function') {
      showToastGlobal(firstError.message, 'error');
    }
  }

  function clearErrors() {
    document.querySelectorAll('.form-error').forEach(el => {
      el.textContent = '';
      el.hidden = true;
    });
    document.querySelectorAll('.form-input.invalid').forEach(el => {
      el.classList.remove('invalid');
      el.removeAttribute('aria-invalid');
    });
  }

  // ---- Success/Error ----
  function showSuccess(booking, roomNumber) {
    const modal = document.getElementById('booking-modal');
    const body = document.getElementById('booking-modal-body');

    if (!modal || !body) return;

    body.innerHTML = `
      <div class="booking-success">
        <div class="booking-success__icon" aria-hidden="true">✓</div>
        <h3 class="booking-success__title">Bokning bekräftad!</h3>
        <p class="booking-success__ref">Referens: <strong>${booking.booking_ref || '#' + booking.id}</strong></p>
        <div class="booking-success__details">
          <div class="booking-success__detail-row">
            <span class="booking-success__detail-label">Rum:</span>
            <span class="booking-success__detail-value">Rum ${roomNumber ? escapeHtml(roomNumber) : '—'}</span>
          </div>
          <div class="booking-success__detail-row">
            <span class="booking-success__detail-label">Incheckning:</span>
            <span class="booking-success__detail-value">${formatDate(booking.check_in)}</span>
          </div>
          <div class="booking-success__detail-row">
            <span class="booking-success__detail-label">Utcheckning:</span>
            <span class="booking-success__detail-value">${formatDate(booking.check_out)}</span>
          </div>
          <div class="booking-success__detail-row">
            <span class="booking-success__detail-label">Pris:</span>
            <span class="booking-success__detail-value">${formatPrice(booking.total_price)} kr</span>
          </div>
        </div>
        <p class="booking-success__note">Spara din referens — visa den vid incheckning.</p>
        <div class="booking-success__actions">
          <button type="button" class="btn btn-primary" id="booking-success-close-btn">Stäng</button>
        </div>
      </div>
    `;

    modal.classList.remove('hidden');

    const closeBtn = document.getElementById('booking-success-close-btn');
    if (closeBtn) {
      closeBtn.addEventListener('click', closeModal);
    }
  }

  function showError(message) {
    const modal = document.getElementById('booking-modal');
    const body = document.getElementById('booking-modal-body');

    if (!modal || !body) return;

    body.innerHTML = `
      <div class="booking-error">
        <div class="booking-error__icon" aria-hidden="true">⚠</div>
        <h3 class="booking-error__title">Fel vid bokning</h3>
        <p class="booking-error__message">${message}</p>
        <div class="booking-error__actions">
          <button type="button" class="btn btn-primary" id="booking-retry-btn">Försök igen</button>
          <button type="button" class="btn btn-secondary" id="booking-close-error-btn">Stäng</button>
        </div>
      </div>
    `;

    modal.classList.remove('hidden');

    // Wire up buttons
    const retryBtn = document.getElementById('booking-retry-btn');
    const closeBtn = document.getElementById('booking-close-error-btn');

    if (retryBtn) {
      retryBtn.addEventListener('click', () => {
        closeModal();
        if (currentRoom) openBookingModal(currentRoom.id);
      });
    }
    if (closeBtn) {
      closeBtn.addEventListener('click', closeModal);
    }
  }

  // ---- Modal ----
  function openBookingModal(roomId) {
    // Find room from API if not cached
    if (!currentRoom || currentRoom.id !== roomId) {
      // Try to find from rooms.js cache or fetch
      if (typeof roomsModule !== 'undefined' && roomsModule.getRooms) {
        const allRooms = roomsModule.getRooms();
        currentRoom = allRooms.find(r => r.id === roomId) || null;
      }
      if (!currentRoom) {
        // Fetch the room from API
        fetch(`${API}/api/rooms/${roomId}/`).then(r => r.json()).then(room => {
          currentRoom = room;
          renderBookingForm(document.getElementById('booking-modal-body'), room);
        }).catch(err => {
          console.error('Failed to load room:', err);
          showError(ERR_MESSAGES.missingRoom);
        });
      } else {
        renderBookingForm(document.getElementById('booking-modal-body'), currentRoom);
      }
    } else {
      renderBookingForm(document.getElementById('booking-modal-body'), currentRoom);
    }

    const modal = document.getElementById('booking-modal');
    if (modal) {
      modal.classList.remove('hidden');
    }
  }

  function closeModal() {
    const modal = document.getElementById('booking-modal');
    const body = document.getElementById('booking-modal-body');

    if (modal) {
      modal.classList.add('hidden');
    }

    if (body) {
      // Reset form
      body.innerHTML = `
        <div class="booking-form__header">
          <h3 class="booking-form__title">Boka Rum</h3>
          <p class="booking-form__subtitle">Välj datum och fyll i uppgifter</p>
        </div>
      `;
    }

    currentRoom = null;
    clearErrors();

    if (typeof showToastGlobal === 'function') {
      // Clear any existing toast
      const toastEl = document.getElementById('toast-notification');
      if (toastEl) toastEl.classList.add('hidden');
    }
  }

  // ---- Public API ----
  function init() {
    // Close modal on backdrop click
    const modal = document.getElementById('booking-modal');
    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) {
          closeModal();
        }
      });
    }

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        const modal = document.getElementById('booking-modal');
        if (modal && !modal.classList.contains('hidden')) {
          closeModal();
        }
        // Also close cancel confirm dialog
        const cancelDialog = document.getElementById('cancel-confirm-dialog');
        if (cancelDialog && cancelDialog.open) {
          cancelDialog.close();
        }
      }
    });
  }

  return {
    init,
    openBookingModal,
    closeModal,
    validateForm,
    showSuccess,
    showError,
    renderBookingForm,
  };
})();
