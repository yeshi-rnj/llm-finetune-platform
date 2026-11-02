import json
import re
from urllib.parse import parse_qs


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class Router:
    def __init__(self):
        self.routes = []

    def add(self, method, pattern, fn, auth=True):
        rx = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[A-Za-z0-9_-]+)", pattern) + "$")
        self.routes.append((method, pattern, rx, fn, auth))

    def match(self, method, path):
        seen = False
        for m, _p, rx, fn, auth in self.routes:
            mt = rx.match(path)
            if mt:
                seen = True
                if m == method:
                    return fn, auth, mt.groupdict()
        if seen:
            raise ApiError(405, "Method not allowed")
        raise ApiError(404, "Not found")

    def patterns(self):
        return [(m, p) for m, p, *_ in self.routes]


class Ctx:
    """Per-request context handed to endpoint functions."""

    def __init__(self, app, handler, params, query_string):
        self.app = app
        self.settings = app.settings
        self.db = app.db
        self.runner = app.runner
        self.handler = handler
        self.params = params
        self.query = {k: v[0] for k, v in parse_qs(query_string).items()}
        self.user = None
        self._body = None

    def body(self, limit):
        if self._body is None:
            raw_len = self.handler.headers.get("Content-Length")
            try:
                n = int(raw_len or 0)
            except ValueError:
                raise ApiError(400, "Invalid Content-Length")
            if n < 0:
                raise ApiError(400, "Invalid Content-Length")
            if n > limit:
                raise ApiError(413, "Request body too large (limit %d bytes)" % limit)
            self._body = self.handler.rfile.read(n) if n else b""
        return self._body

    def json(self):
        raw = self.body(1024 * 1024)
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "Body must be valid JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "JSON body must be an object")
        return data
