// Sea View Hotel — lightweight JS
// Manages navigation, module initialization, and global helpers.

// Global API base used by modules that still reference `${API}` directly
// (e.g. booking-flow.js). Kept here so the orchestrator remains the single
// owner of shared bootstrap globals. Derived from the served index.html URL
// (same mechanism as utils/api.js API_BASE) so both bare mode (app at /) and
// a prefixed subpath mount work — no hardcoded prefix.
const API = new URL('.', document.baseURI).pathname.replace(/\/$/, '');

// ============================================================================
// Navigation
// ============================================================================

document.querySelectorAll('nav a[data-page]').forEach((link) => {
  link.addEventListener("click", (e) => {
    e.preventDefault();
    const page = link.dataset.page;
    showPage(page);
    document.querySelectorAll("nav a").forEach((a) => a.classList.remove("active"));
    link.classList.add("active");
  });
});

function showPage(page) {
  // Hide all page sections
  document.querySelectorAll("main > section").forEach((s) => s.classList.add("hidden"));

  const target = document.getElementById(`page-${page}`);
  if (target) {
    target.classList.remove("hidden");
  }

  // Initialize page-specific modules
  if (page === "rooms" && typeof initRooms === "function") {
    initRooms();
  }
  if (page === "bookings" && typeof bookingsModule !== "undefined") {
    bookingsModule.init();
  }
  if (page === "calendar" && typeof calendarModule !== "undefined") {
    calendarModule.init();
  }
}

// ============================================================================
// Booking Modal — delegates to booking-flow.js
// ============================================================================

/**
 * openBooking — called from rooms.js when user clicks "Boka" on a room card.
 * @param {number|string} roomId - Room ID
 */
function openBooking(roomId) {
  if (typeof bookingFlowModule !== "undefined") {
    bookingFlowModule.openBookingModal(roomId);
  }
}

function closeBooking() {
  if (typeof bookingFlowModule !== "undefined") {
    bookingFlowModule.closeModal();
  }
}

// ============================================================================
// Room Detail Modal — delegates to rooms.js
// ============================================================================

function openRoomDetail(roomId) {
  if (typeof roomsModule !== "undefined" && roomsModule.showDetail) {
    roomsModule.showDetail(roomId);
  }
}

function closeRoomDetail() {
  if (typeof roomsModule !== "undefined" && roomsModule.hideDetail) {
    roomsModule.hideDetail();
  }
}

// ============================================================================
// Dark Mode Toggle
// ============================================================================

function initDarkMode() {
  const toggle = document.getElementById("dark-mode-toggle");
  if (!toggle) return;

  // Load saved preference
  const saved = localStorage.getItem("darkMode");
  if (saved === "true") {
    document.body.classList.add("dark-mode");
    toggle.textContent = "☀️";
  }

  toggle.addEventListener("click", () => {
    document.body.classList.toggle("dark-mode");
    const isDark = document.body.classList.contains("dark-mode");
    localStorage.setItem("darkMode", isDark);
    toggle.textContent = isDark ? "☀️" : "🌙";
  });
}

// ============================================================================
// Hero CTA — smooth scroll to rooms
// ============================================================================

function initHero() {
  const heroCta = document.querySelector('.site-hero__cta[data-page="rooms"]');
  if (heroCta) {
    heroCta.addEventListener('click', (e) => {
      e.preventDefault();
      // Find and click the rooms nav link
      const roomsLink = document.querySelector('nav a[data-page="rooms"]');
      if (roomsLink) {
        roomsLink.click();
      }
    });
  }
}

// ============================================================================
// Initialization
// ============================================================================

document.addEventListener("DOMContentLoaded", () => {
  // Initialize dark mode first (applies before rendering)
  initDarkMode();

  // Initialize hero
  initHero();

  // Initialize rooms page (from render-rooms.js)
  if (typeof initRooms === "function") {
    initRooms();
  } else {
    showPage("rooms");
    document.getElementById("page-rooms")?.classList.remove("hidden");
  }

  // Initialize navigation highlighting
  const roomsLink = document.querySelector('nav a[data-page="rooms"]');
  if (roomsLink) roomsLink.classList.add("active");

  // Initialize booking flow module (always, so modal is ready)
  if (typeof bookingFlowModule !== "undefined") {
    bookingFlowModule.init();
  }
});
