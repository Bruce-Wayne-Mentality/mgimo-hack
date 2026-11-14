"""Serve the built React app (apps/web/dist) with a server-side login gate.

Every screen except the public ones redirects to /login when there is no valid
session, so protected pages are never shown before sign-in. Data stays behind
the API, which independently answers 401 without a session.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

LOGIN_PATH = "/login"
# Screens that must open without an account (section 6: login, document check,
# shared profile). The last two arrive with K2/K10.
PUBLIC_PREFIXES = ("/verify/", "/s/")
NOT_PAGES = ("/api/", "/docs", "/redoc", "/openapi.json", "/health", "/assets/")

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        # Google Fonts (Unbounded, Onest, JetBrains Mono) are the only third-party origins.
        "default-src 'self'; img-src 'self' data:; style-src 'self' https://fonts.googleapis.com; "
        "script-src 'self'; connect-src 'self'; font-src 'self' https://fonts.gstatic.com; "
        "manifest-src 'self'; worker-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "X-Frame-Options": "DENY",
}
# Swagger UI loads its bundle from a CDN and uses inline code.
CSP_EXEMPT = ("/docs", "/redoc")


def safe_next(value: str | None) -> str:
    """Only same-site relative paths; blocks //evil.example and scheme tricks."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    if value == LOGIN_PATH or value.startswith(LOGIN_PATH + "?"):
        return "/"
    return value


def add_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        exempt = request.url.path.startswith(CSP_EXEMPT)
        for name, value in SECURITY_HEADERS.items():
            if exempt and name == "Content-Security-Policy":
                continue
            response.headers.setdefault(name, value)
        return response


def register_web(app: FastAPI, dist: Path) -> None:
    dist = dist.resolve()
    index = dist / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"Нет собранного фронтенда: {index}. Выполните npm run build в apps/web.")

    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/sw.js", include_in_schema=False)
    def service_worker() -> FileResponse:
        return FileResponse(
            dist / "sw.js", media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
        )

    def page() -> FileResponse:
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str, request: Request) -> Response:
        url_path = "/" + path
        if url_path.startswith(NOT_PAGES):
            return JSONResponse({"error": {"code": "not_found", "message": "Не найдено."}}, status_code=404)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist) and candidate != index:
            return FileResponse(candidate)

        current = await request.app.state.optional_session(request)
        if url_path == LOGIN_PATH:
            if current is not None:
                return RedirectResponse(safe_next(request.query_params.get("next")), status_code=303)
            return page()
        if url_path.startswith(PUBLIC_PREFIXES):
            return page()
        if current is None:
            target = url_path + (f"?{request.url.query}" if request.url.query else "")
            location = LOGIN_PATH if target == "/" else f"{LOGIN_PATH}?next={quote(target, safe='/')}"
            return RedirectResponse(location, status_code=303)
        return page()
