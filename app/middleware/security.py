from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# /api/hot covers the Phase A override JSON API. /api/admin covers the
# campaigns + clubs + Phase 3 hot dashboard mutation endpoints.
CSRF_PROTECTED_PREFIXES = ("/admin", "/api/admin", "/api/hot", "/manual")

# Public render endpoints are designed to be embedded on third-party sites —
# ad creatives, partner pages, Google Ad Manager. They expose no sensitive
# data, so they must opt out of the same-site Cross-Origin-Resource-Policy
# lock; otherwise a cross-origin <img>/<iframe> (e.g. a GAM creative pulling
# /cube/worldcup/odds.png) is blocked by the browser. Everything else stays
# same-site.
PUBLIC_EMBED_PREFIXES = ("/cube", "/r/", "/hot", "/render", "/club")


def _origin_from_request(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}".lower()


def _header_origin(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".lower()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # Keep the admin panel out of search indexes — this is the header that
        # actually prevents indexing (robots.txt only blocks crawling, and a
        # disallowed URL can still surface in results). Admin pages already
        # require auth, so this is defense-in-depth.
        if request.url.path.startswith(("/admin", "/api/admin")):
            response.headers.setdefault("X-Robots-Tag", "noindex, nofollow, noarchive")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        # Embeddable public render endpoints get cross-origin so third-party
        # sites (Google Ad Manager etc.) can load them; all else stays same-site.
        corp = (
            "cross-origin"
            if request.url.path.startswith(PUBLIC_EMBED_PREFIXES)
            else "same-site"
        )
        response.headers.setdefault("Cross-Origin-Resource-Policy", corp)
        # `unsafe-eval` is required by:
        #   - Alpine.js: compiles every x-show/x-text/x-model/etc. directive
        #     into a runtime Function() — without it, every binding silently
        #     no-ops and the admin pages render as static templates with no
        #     fetched data (root cause of "browse shows nothing while PNG
        #     works").
        #   - Tailwind CDN JIT: also uses Function() to compile class names
        #     at runtime.
        # `style-src 'unsafe-inline'` is required by Tailwind CDN injecting
        # styles dynamically.
        # Follow-up (out of scope here): replace the Tailwind CDN with a
        # pre-built CSS bundle and swap Alpine for its CSP-friendly build
        # so we can drop both `unsafe-eval` and the third-party CDN hosts.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "https://cdn.tailwindcss.com https://unpkg.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data: https:; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )
        if request.headers.get("x-forwarded-proto") == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


class SameOriginUnsafeMethodMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method.upper() in UNSAFE_METHODS and path.startswith(CSRF_PROTECTED_PREFIXES):
            expected = _origin_from_request(request)
            actual = _header_origin(request.headers.get("origin"))
            if actual is None:
                actual = _header_origin(request.headers.get("referer"))
            if actual != expected:
                return Response("Forbidden", status_code=403)
        return await call_next(request)
