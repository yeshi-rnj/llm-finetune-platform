import json
import random
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.config import Settings
from app.server import App, serve_in_thread

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


def make_csv(n_per_class=40, seed=1):
    rnd = random.Random(seed)
    pos = ["great", "excellent", "love", "wonderful", "fantastic", "happy", "amazing", "perfect"]
    neg = ["terrible", "awful", "hate", "horrible", "worst", "sad", "broken", "useless"]
    filler = ["the", "product", "service", "really", "was", "very", "today", "this", "item", "and"]
    lines = ["text,label"]
    for _ in range(n_per_class):
        lines.append('"%s",positive' % " ".join(rnd.sample(filler, 4) + rnd.sample(pos, 2)))
        lines.append('"%s",negative' % " ".join(rnd.sample(filler, 4) + rnd.sample(neg, 2)))
    return "\n".join(lines) + "\n"


class Client:
    def __init__(self, base, token=None):
        self.base, self.token = base, token

    def req(self, method, path, body=None, raw=None, ctype=None, headers=None):
        h = dict(headers or {})
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        data = None
        if raw is not None:
            data, h["Content-Type"] = raw, ctype or "text/csv"
        elif body is not None:
            data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return resp.status, self._parse(resp.read()), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, self._parse(e.read()), e.headers

    @staticmethod
    def _parse(b):
        try:
            return json.loads(b)
        except ValueError:
            return b

    def get(self, p, **k): return self.req("GET", p, **k)
    def post(self, p, body=None, **k): return self.req("POST", p, body=body, **k)
    def delete(self, p, **k): return self.req("DELETE", p, **k)


class Env:
    """A real server on an ephemeral port with an isolated temp data dir."""

    def __init__(self, **overrides):
        self.tmp = tempfile.mkdtemp(prefix="ft-test-")
        env = {"DATA_DIR": self.tmp, "FRONTEND_DIR": str(FRONTEND), "LOG_REQUESTS": "0",
               "JWT_SECRET": "t" * 40, "CORS_ORIGINS": "http://localhost:5173"}
        env.update(overrides)
        self.settings = Settings(env)
        self.app = App(self.settings)
        self.srv, _ = serve_in_thread(self.app)
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def client(self, token=None):
        return Client(self.base, token)

    def signup(self, email, pw="password123"):
        c = self.client()
        st, body, _ = c.post("/api/auth/register", {"email": email, "password": pw})
        assert st == 201, (st, body)
        return Client(self.base, body["token"]), body["user"]

    def wait_job(self, c, jid, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            st, j, _ = c.get("/api/jobs/" + jid)
            assert st == 200, (st, j)
            if j["status"] in ("succeeded", "failed"):
                return j
            time.sleep(0.2)
        raise AssertionError("job did not finish in %ss" % timeout)

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)
