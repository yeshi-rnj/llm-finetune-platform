import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from . import handlers, security
from .config import Settings
from .core import ApiError, Ctx, Router
from .db import Database, migrate
from .runner import JobRunner

log = logging.getLogger("server")

# Explicit map: mimetypes consults the Windows registry, which can map .js to text/plain
# (and `nosniff` would then stop the browser executing the script).
MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml",
        ".png": "image/png", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8"}


class App:
    def __init__(self, settings=None):
        self.settings = settings or Settings()
        self.settings.ensure_dirs()
        self.db = Database(self.settings.db_path)
        migrate(self.db)
        self.runner = JobRunner(self.settings, self.db)
        self.router = Router()
        handlers.register_routes(self.router)


class Handler(BaseHTTPRequestHandler):
    server_version = "FineTunePlatform"
    timeout = 60  # per-socket-operation timeout; drops stalled/slowloris clients
    sys_version = ""

    def log_message(self, fmt, *args):
        if self.server.app.settings.log_requests:
            log.info("%s %s", self.address_string(), fmt % args)

    # -- helpers
    def _cors_headers(self):
        origin = self.headers.get("Origin")
        allowed = self.server.app.settings.cors_origins
        if origin and ("*" in allowed or origin in allowed):
            return [("Access-Control-Allow-Origin", origin), ("Vary", "Origin"),
                    ("Access-Control-Allow-Headers", "Authorization, Content-Type"),
                    ("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"),
                    ("Access-Control-Max-Age", "600")]
        return []

    def _security_headers(self):
        s = self.server.app.settings
        connect = "'self'" + (" " + s.api_base_url if s.api_base_url else "")
        return [("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"),
                ("Referrer-Policy", "no-referrer"),
                ("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                 "connect-src %s; img-src 'self' data:; frame-ancestors 'none'" % connect)]

    def _send(self, status, body=b"", ctype="application/json", extra=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in list(self._cors_headers()) + self._security_headers() + list(extra):
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, payload):
        self._send(status, json.dumps(payload).encode("utf-8"))

    def _authenticate(self):
        h = self.headers.get("Authorization", "")
        if not h.startswith("Bearer "):
            raise ApiError(401, "Authentication required")
        uid = security.read_token(h[7:].strip(), self.server.app.settings.jwt_secret)
        if not uid:
            raise ApiError(401, "Invalid or expired token")
        with self.server.app.db.conn() as c:
            u = c.execute("SELECT id,email FROM users WHERE id=?", (uid,)).fetchone()
        if not u:
            raise ApiError(401, "Invalid or expired token")
        return {"id": u["id"], "email": u["email"]}

    def _static(self, path):
        s = self.server.app.settings
        if path == "/config.js":
            body = ("window.APP_CONFIG = %s;\n" % json.dumps({"apiBase": s.api_base_url})).encode()
            return self._send(200, body, "application/javascript; charset=utf-8")
        rel = "index.html" if path in ("", "/") else unquote(path).lstrip("/")
        target = (s.frontend_dir / rel).resolve()
        if not target.is_relative_to(s.frontend_dir) or not target.is_file() or target.name.startswith("."):
            raise ApiError(404, "Not found")
        ctype = MIME.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

    # -- dispatch
    def _handle(self, method):
        app = self.server.app
        parts = urlsplit(self.path)
        path = parts.path
        try:
            if path.startswith("/api/"):
                fn, auth, params = app.router.match(method, path)
                ctx = Ctx(app, self, params, parts.query)
                if auth:
                    ctx.user = self._authenticate()
                res = fn(ctx)
                status, payload = res if isinstance(res, tuple) else (200, res)
                self._json(status, payload)
            elif method in ("GET", "HEAD"):
                self._static(path)
            else:
                raise ApiError(405, "Method not allowed")
        except ApiError as e:
            self._json(e.status, {"error": e.message})
        except TimeoutError:  # client stalled mid-request; not a server fault
            self.close_connection = True
            try:
                self._json(408, {"error": "Request timed out"})
            except OSError:
                pass
        except Exception:
            log.exception("unhandled error on %s %s", method, path)
            self._json(500, {"error": "Internal server error"})

    def do_GET(self): self._handle("GET")
    def do_HEAD(self): self._handle("HEAD")
    def do_POST(self): self._handle("POST")
    def do_DELETE(self): self._handle("DELETE")
    def do_PUT(self): self._handle("PUT")
    def do_PATCH(self): self._handle("PATCH")

    def do_OPTIONS(self):
        self._send(204)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, app):
        super().__init__(addr, Handler)
        self.app = app


def make_server(app, host=None, port=None):
    srv = Server((host or app.settings.host, app.settings.port if port is None else port), app)
    app.runner.start()
    return srv


def serve_in_thread(app, host="127.0.0.1", port=0):
    srv = make_server(app, host, port)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, t
