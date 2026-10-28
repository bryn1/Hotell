// ============================================================================
// utils/escape.js — the ONE quote-safe HTML escape util
// ============================================================================
//
// Root cause of the audit P0 (202610271433 FINDINGS-security §P0-1) was four
// drifted per-module copies of escapeHtml: two were div-based (no quote
// escaping), one missed the apostrophe. A renderer that only encodes & < > is
// safe in TEXT position but breaks inside a quoted attribute — and this code
// base interpolates user data into attribute templates (aria-label, title,
// alt, data-*), so quote-escaping is mandatory here. This is the single
// implementation; the per-module copies are deleted (fix-one-place law).
//
// No dependencies. Loaded FIRST of the static/js files in templates/index.html
// (before toasts.js and every renderer that calls escapeHtml).

/**
 * Escape a value for interpolation into HTML text AND double-quoted
 * attribute values. Explicit replacements cover & < > " ' (the div/
 * textContent trick escapes no quotes — see header comment).
 * @param {*} str - value to escape (coerced with String())
 * @returns {string} HTML-safe string
 */
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
