"""Demo write guard — per-visitor rate limit for a publicly reachable demo (MC 2034.2).

This app is published on a public URL (Cloudflare Tunnel -> nginx -> 127.0.0.1), so every
mutating endpoint is world-reachable. This middleware keeps a demo a demo: a token bucket
per visitor, applied ONLY to mutating methods, so browsing stays unthrottled.

Visitor identity: ``CF-Connecting-IP`` is the ONLY trusted header (card
11535). The Cloudflare edge overwrites it on every routed request, so on the
public path it is the only IP header an anonymous client cannot forge. The
``X-Forwarded-For`` trust was dropped entirely: nginx's
$proxy_add_x_forwarded_for APPENDS the client's own header list, so the first
entry — the one previously trusted — is attacker-supplied, and one request
header made this guard not exist. Direct-origin traffic (no CF header) falls
back to ``request.client.host``.

No third-party dependencies: the render pipeline builds a venv per app from requirements.txt,
and a rate limiter is not worth a new pinned dependency.
"""
from __future__ import annotations

import time
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CAPACITY = 10           # burst a visitor may make back-to-back
WINDOW_SECONDS = 300.0  # bucket refills fully over this window
MAX_TRACKED = 5000      # bound memory under a distributed flood


def visitor_ip(request: Request) -> str:
    """Identity for the real visitor — CF-Connecting-IP only (card 11535).

    The Cloudflare edge overwrites CF-Connecting-IP on every routed request,
    so on the public path it is the only IP header an anonymous client cannot
    forge. X-Forwarded-For is deliberately NOT trusted: nginx's
    $proxy_add_x_forwarded_for appends the client's own header list, so its
    first entry — the one previously trusted here — is attacker-supplied and
    one request header reset the visitor identity at will (audit P1).
    Direct-origin traffic (no CF header) falls back to the socket peer.
    """
    cf = (request.headers.get("cf-connecting-ip") or "").strip()
    if cf:
        return cf
    client = request.client
    return client.host if client else "unknown"


class DemoWriteGuard(BaseHTTPMiddleware):
    """Token-bucket rate limit on mutating requests, keyed per visitor."""

    def __init__(self, app, capacity: int = CAPACITY, window: float = WINDOW_SECONDS) -> None:
        super().__init__(app)
        self._capacity = float(capacity)
        self._rate = float(capacity) / float(window)
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = Lock()

    def _prune_locked(self) -> None:
        # Drop buckets that have refilled (idle visitors carry no state worth
        # keeping). If that is not enough, evict least-recently-seen buckets
        # one at a time until back under MAX_TRACKED (card 11535, audit P1):
        # the previous wholesale .clear() handed every already-throttled
        # visitor a full bucket back — a fail-open an identity-flooding
        # attacker reached at will.
        #
        # Fail-closed for spent buckets: a missing key re-enters _take with a
        # FULL bucket, so a bucket with < 1 token left is NEVER evicted —
        # evicting it would revive it. Only buckets that can still serve a
        # request (>= 1 token) are candidates; dropping one of those costs an
        # idle visitor a few unspent tokens at worst, never a free refill.
        # In practice the candidate set is exactly the identity-flood rows,
        # which is why the cap holds without ever touching a spent bucket.
        self._buckets = {
            key: val for key, val in self._buckets.items() if val[0] < self._capacity - 0.001
        }
        if len(self._buckets) > MAX_TRACKED:
            candidates = sorted(
                (
                    (val[1], key)
                    for key, val in self._buckets.items()
                    if val[0] >= 1.0
                ),
            )
            for _, key in candidates:
                if len(self._buckets) <= MAX_TRACKED:
                    break
                del self._buckets[key]

    def _take(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._buckets) > MAX_TRACKED:
                self._prune_locked()
            tokens, last = self._buckets.get(key, (self._capacity, now))
            tokens = min(self._capacity, tokens + (now - last) * self._rate)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            return True

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in WRITE_METHODS and not self._take(visitor_ip(request)):
            return JSONResponse(
                {
                    "detail": (
                        "För många ändringar från samma besökare. "
                        "Det här är en demo — vänta en stund och försök igen."
                    )
                },
                status_code=429,
                headers={"Retry-After": str(int(WINDOW_SECONDS))},
            )
        return await call_next(request)
