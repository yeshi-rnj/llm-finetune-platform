import json
import sqlite3
import time
import unittest
import urllib.request

import jwt

from app import trainer
from app.config import Settings
from app.db import Database, migrate
from tests.helpers import Env, make_csv

try:
    import torch  # noqa: F401
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Env()

    @classmethod
    def tearDownClass(cls):
        cls.env.close()


class TestAuth(Base):
    def test_register_login_me(self):
        c, user = self.env.signup("a1@example.com")
        st, body, _ = c.get("/api/auth/me")
        self.assertEqual((st, body["user"]["email"]), (200, "a1@example.com"))
        st, body, _ = self.env.client().post("/api/auth/login", {"email": "A1@Example.com", "password": "password123"})
        self.assertEqual(st, 200)
        self.assertIn("token", body)

    def test_duplicate_and_validation(self):
        self.env.signup("dup@example.com")
        c = self.env.client()
        self.assertEqual(c.post("/api/auth/register", {"email": "dup@example.com", "password": "password123"})[0], 409)
        self.assertEqual(c.post("/api/auth/register", {"email": "nope", "password": "password123"})[0], 400)
        self.assertEqual(c.post("/api/auth/register", {"email": "x@example.com", "password": "short"})[0], 400)
        self.assertEqual(c.post("/api/auth/register", {"email": "x@example.com", "password": 12345678})[0], 400)
        self.assertEqual(c.req("POST", "/api/auth/register", raw=b"{not json", ctype="application/json")[0], 400)
        self.assertEqual(c.req("POST", "/api/auth/register", raw=b"[1,2]", ctype="application/json")[0], 400)

    def test_wrong_password_and_unknown_user_same_error(self):
        self.env.signup("w@example.com")
        c = self.env.client()
        s1, b1, _ = c.post("/api/auth/login", {"email": "w@example.com", "password": "wrongwrong"})
        s2, b2, _ = c.post("/api/auth/login", {"email": "ghost@example.com", "password": "wrongwrong"})
        self.assertEqual((s1, s2), (401, 401))
        self.assertEqual(b1, b2)

    def test_token_rejections(self):
        c = self.env.client()
        self.assertEqual(c.get("/api/projects")[0], 401)
        self.assertEqual(self.env.client("garbage").get("/api/projects")[0], 401)
        secret = self.env.settings.jwt_secret
        expired = jwt.encode({"sub": "x", "exp": int(time.time()) - 10}, secret, algorithm="HS256")
        self.assertEqual(self.env.client(expired).get("/api/projects")[0], 401)
        forged = jwt.encode({"sub": "x", "exp": int(time.time()) + 999}, "wrong-secret-wrong-secret-wrong-secret", algorithm="HS256")
        self.assertEqual(self.env.client(forged).get("/api/projects")[0], 401)
        # valid signature but user does not exist
        ghost = jwt.encode({"sub": "nonexistent", "exp": int(time.time()) + 999}, secret, algorithm="HS256")
        self.assertEqual(self.env.client(ghost).get("/api/projects")[0], 401)
        # alg=none token
        import base64
        b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
        none_tok = b({"alg": "none", "typ": "JWT"}) + "." + b({"sub": "x", "exp": int(time.time()) + 999}) + "."
        self.assertEqual(self.env.client(none_tok).get("/api/projects")[0], 401)

    def test_password_not_stored_plaintext(self):
        self.env.signup("hash@example.com", "my-secret-pw-123")
        with self.env.app.db.conn() as c:
            h = c.execute("SELECT password_hash FROM users WHERE email='hash@example.com'").fetchone()[0]
        self.assertTrue(h.startswith("scrypt$"))
        self.assertNotIn("my-secret-pw-123", h)


class TestProjectsAndDatasets(Base):
    def test_project_crud(self):
        c, _ = self.env.signup("p1@example.com")
        self.assertEqual(c.post("/api/projects", {"name": "  "})[0], 400)
        self.assertEqual(c.post("/api/projects", {"name": "x" * 101})[0], 400)
        st, p, _ = c.post("/api/projects", {"name": "Demo", "description": "d"})
        self.assertEqual(st, 201)
        st, lst, _ = c.get("/api/projects")
        self.assertEqual([x["id"] for x in lst["projects"]], [p["id"]])
        self.assertEqual(c.get("/api/projects/" + p["id"])[1]["name"], "Demo")
        self.assertEqual(c.delete("/api/projects/" + p["id"])[0], 200)
        self.assertEqual(c.get("/api/projects/" + p["id"])[0], 404)

    def test_dataset_upload_validation_and_preview(self):
        c, _ = self.env.signup("d1@example.com")
        pid = c.post("/api/projects", {"name": "P"})[1]["id"]
        up = "/api/projects/%s/datasets?name=reviews.csv" % pid
        st, ds, _ = c.req("POST", up, raw=make_csv().encode())
        self.assertEqual(st, 201, ds)
        self.assertEqual((ds["row_count"], ds["labels"]), (80, {"positive": 40, "negative": 40}))
        st, det, _ = c.get("/api/datasets/" + ds["id"])
        self.assertEqual((st, len(det["preview"])), (200, 10))
        bad = {
            "no columns": b"a,b\n1,2\n",
            "too few rows": b"text,label\nhi,a\nyo,b\n",
            "one label": ("text,label\n" + "\n".join("t%d,a" % i for i in range(20))).encode(),
            "singleton label": ("text,label\n" + "\n".join("t%d,a" % i for i in range(20)) + "\nz,b\n").encode(),
            "not utf8": b"text,label\n\xff\xfe,a\n",
            "empty": b"",
        }
        for why, raw in bad.items():
            st, body, _ = c.req("POST", up, raw=raw)
            self.assertEqual(st, 400, (why, body))

    def test_upload_size_limit(self):
        env = Env(MAX_UPLOAD_BYTES="2000")
        try:
            c, _ = env.signup("big@example.com")
            pid = c.post("/api/projects", {"name": "P"})[1]["id"]
            st, body, _ = c.req("POST", "/api/projects/%s/datasets" % pid, raw=make_csv().encode())
            self.assertEqual(st, 413, body)
        finally:
            env.close()

    def test_delete_dataset_removes_file(self):
        import os
        c, _ = self.env.signup("d2@example.com")
        pid = c.post("/api/projects", {"name": "P"})[1]["id"]
        ds = c.req("POST", "/api/projects/%s/datasets" % pid, raw=make_csv().encode())[1]
        path = os.path.join(self.env.settings.datasets_dir, ds["id"] + ".csv")
        self.assertTrue(os.path.exists(path))
        self.assertEqual(c.delete("/api/datasets/" + ds["id"])[0], 200)
        self.assertFalse(os.path.exists(path))


class TestTrainingPipeline(Base):
    """upload -> train job -> model registry -> evaluation -> inference, for real (scikit-learn)."""

    def test_full_pipeline(self):
        c, _ = self.env.signup("t1@example.com")
        pid = c.post("/api/projects", {"name": "P"})[1]["id"]
        ds = c.req("POST", "/api/projects/%s/datasets" % pid, raw=make_csv().encode())[1]
        st, job, _ = c.post("/api/projects/%s/jobs" % pid, {"dataset_id": ds["id"], "model_name": "sentiment-v1",
                                                         "params": {"C": 5, "ngram_max": 2}})
        self.assertEqual(st, 201, job)
        self.assertEqual(job["status"], "queued")
        done = self.env.wait_job(c, job["id"])
        self.assertEqual(done["status"], "succeeded", done)
        self.assertGreater(done["metrics"]["accuracy"], 0.9)
        self.assertEqual(done["metrics"]["n"], 16)
        # registry
        models = c.get("/api/projects/%s/models" % pid)[1]["models"]
        self.assertEqual([m["name"] for m in models], ["sentiment-v1"])
        mid = models[0]["id"]
        self.assertEqual(done["model_id"], mid)
        self.assertEqual(sorted(models[0]["labels"]), ["negative", "positive"])
        # evaluation
        st, ev, _ = c.post("/api/models/%s/evaluate" % mid)
        self.assertEqual(st, 201, ev)
        self.assertEqual(ev["metrics"]["accuracy"], done["metrics"]["accuracy"])
        self.assertEqual(len(ev["metrics"]["confusion_matrix"]["matrix"]), 2)
        self.assertEqual(len(c.get("/api/models/%s/evaluations" % mid)[1]["evaluations"]), 1)
        # inference
        st, out, _ = c.post("/api/models/%s/predict" % mid, {"texts": ["this was excellent and wonderful", "awful terrible broken"]})
        self.assertEqual(st, 200, out)
        self.assertEqual([p["label"] for p in out["predictions"]], ["positive", "negative"])
        self.assertAlmostEqual(sum(out["predictions"][0]["probabilities"].values()), 1.0, places=2)
        # input validation
        for bad in ({"texts": []}, {"texts": "x"}, {"texts": [""]}, {"texts": [1]}, {"texts": ["a"] * 101}, {}):
            self.assertEqual(c.post("/api/models/%s/predict" % mid, bad)[0], 400, bad)
        # delete model removes artifacts, evaluation cascades
        import os
        with self.env.app.db.conn() as db:
            art = db.execute("SELECT artifact_path FROM models WHERE id=?", (mid,)).fetchone()[0]
        self.assertTrue(os.path.exists(art))
        self.assertEqual(c.delete("/api/models/" + mid)[0], 200)
        self.assertFalse(os.path.exists(art))
        self.assertEqual(c.post("/api/models/%s/predict" % mid, {"texts": ["x"]})[0], 404)

    def test_job_validation(self):
        c, _ = self.env.signup("t2@example.com")
        pid = c.post("/api/projects", {"name": "P"})[1]["id"]
        ds = c.req("POST", "/api/projects/%s/datasets" % pid, raw=make_csv().encode())[1]
        url = "/api/projects/%s/jobs" % pid
        cases = [
            ({}, 400), ({"dataset_id": ds["id"], "method": "nope"}, 400),
            ({"dataset_id": ds["id"], "params": {"C": -1}}, 400), ({"dataset_id": ds["id"], "params": {"C": "a"}}, 400),
            ({"dataset_id": ds["id"], "params": {"C": True}}, 400), ({"dataset_id": ds["id"], "params": {"evil": 1}}, 400),
            ({"dataset_id": ds["id"], "params": {"test_size": 0.9}}, 400), ({"dataset_id": ds["id"], "params": []}, 400),
            ({"dataset_id": "does-not-exist"}, 404),
        ]
        for body, want in cases:
            self.assertEqual(c.post(url, body)[0], want, body)

    def test_job_fails_cleanly_when_dataset_deleted(self):
        c, _ = self.env.signup("t3@example.com")
        pid = c.post("/api/projects", {"name": "P"})[1]["id"]
        ds = c.req("POST", "/api/projects/%s/datasets" % pid, raw=make_csv().encode())[1]
        # pause the worker's view of the file by deleting right after submit is racy; instead delete first via DB row
        c.delete("/api/datasets/" + ds["id"])
        self.assertEqual(c.post("/api/projects/%s/jobs" % pid, {"dataset_id": ds["id"]})[0], 404)

    @unittest.skipIf(HAS_TORCH, "torch is installed; this test covers the missing-dependency path")
    def test_lora_without_torch_fails_with_clear_message(self):
        c, _ = self.env.signup("t4@example.com")
        pid = c.post("/api/projects", {"name": "P"})[1]["id"]
        ds = c.req("POST", "/api/projects/%s/datasets" % pid, raw=make_csv().encode())[1]
        st, job, _ = c.post("/api/projects/%s/jobs" % pid, {"dataset_id": ds["id"], "method": "lora-causal-lm"})
        self.assertEqual(st, 201, job)
        done = self.env.wait_job(c, job["id"])
        self.assertEqual(done["status"], "failed")
        self.assertIn("requires torch", done["error"])
        self.assertEqual(c.get("/api/projects/%s/models" % pid)[1]["models"], [])

    def test_lora_param_validation(self):
        ok = trainer.validate_params("lora-causal-lm", {"base_model": "distilbert-base-uncased", "epochs": 2})
        self.assertEqual(ok["epochs"], 2)
        for bad in ("../../etc", "/abs/path", "a/b/c", "x" * 200, "", 5):
            with self.assertRaises(ValueError, msg=repr(bad)):
                trainer.validate_params("lora-causal-lm", {"base_model": bad})


class TestIsolation(Base):
    """User B must not be able to read, change, run or delete anything of user A's."""

    def test_cross_tenant_access_is_denied(self):
        a, _ = self.env.signup("alice@example.com")
        b, _ = self.env.signup("bob@example.com")
        pid = a.post("/api/projects", {"name": "A-proj"})[1]["id"]
        ds = a.req("POST", "/api/projects/%s/datasets" % pid, raw=make_csv().encode())[1]
        job = a.post("/api/projects/%s/jobs" % pid, {"dataset_id": ds["id"]})[1]
        done = self.env.wait_job(a, job["id"])
        mid = done["model_id"]
        self.assertIsNotNone(mid)
        denied = [
            ("GET", "/api/projects/" + pid), ("DELETE", "/api/projects/" + pid),
            ("GET", "/api/projects/%s/datasets" % pid), ("GET", "/api/projects/%s/jobs" % pid),
            ("GET", "/api/projects/%s/models" % pid),
            ("GET", "/api/datasets/" + ds["id"]), ("DELETE", "/api/datasets/" + ds["id"]),
            ("GET", "/api/jobs/" + job["id"]),
            ("GET", "/api/models/" + mid), ("DELETE", "/api/models/" + mid),
            ("POST", "/api/models/%s/evaluate" % mid), ("GET", "/api/models/%s/evaluations" % mid),
        ]
        for method, path in denied:
            st, body, _ = b.req(method, path)
            self.assertEqual(st, 404, (method, path, body))
        self.assertEqual(b.post("/api/models/%s/predict" % mid, {"texts": ["great"]})[0], 404)
        self.assertEqual(b.req("POST", "/api/projects/%s/datasets" % pid, raw=make_csv().encode())[0], 404)
        self.assertEqual(b.post("/api/projects/%s/jobs" % pid, {"dataset_id": ds["id"]})[0], 404)
        # B's own project must not accept A's dataset id
        bpid = b.post("/api/projects", {"name": "B-proj"})[1]["id"]
        self.assertEqual(b.post("/api/projects/%s/jobs" % bpid, {"dataset_id": ds["id"]})[0], 404)
        # listings are scoped
        self.assertEqual(b.get("/api/projects")[1]["projects"][0]["id"], bpid)
        self.assertEqual(len(b.get("/api/projects")[1]["projects"]), 1)
        # A's data is intact after B's attempts
        self.assertEqual(a.get("/api/projects/" + pid)[0], 200)
        self.assertEqual(a.get("/api/models/" + mid)[0], 200)
        self.assertEqual(a.post("/api/models/%s/predict" % mid, {"texts": ["great"]})[0], 200)

    def test_sql_injection_in_ids_is_inert(self):
        a, _ = self.env.signup("sqli@example.com")
        from urllib.parse import quote
        for evil in ("1' OR '1'='1", "x' OR 1=1--", "../../etc/passwd", "a;DROP TABLE users"):
            for prefix in ("/api/projects/", "/api/datasets/", "/api/jobs/", "/api/models/"):
                st, _, _ = a.get(prefix + quote(evil, safe=""))
                self.assertEqual(st, 404, (prefix, evil))
        self.assertEqual(a.post("/api/auth/login", {"email": "' OR 1=1 --", "password": "x"})[0], 401)


class TestHttpLayer(Base):
    def _raw(self, method, path, headers=None):
        r = urllib.request.Request(self.env.base + path, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def test_cors_preflight_allowed_and_denied(self):
        st, h, _ = self._raw("OPTIONS", "/api/projects", {"Origin": "http://localhost:5173",
                                                         "Access-Control-Request-Method": "POST",
                                                         "Access-Control-Request-Headers": "authorization,content-type"})
        self.assertEqual(st, 204)
        self.assertEqual(h["Access-Control-Allow-Origin"], "http://localhost:5173")
        self.assertIn("Authorization", h["Access-Control-Allow-Headers"])
        st, h, _ = self._raw("OPTIONS", "/api/projects", {"Origin": "http://evil.example"})
        self.assertEqual(st, 204)
        self.assertIsNone(h["Access-Control-Allow-Origin"])
        # actual (non-preflight) response also carries the header for allowed origins only
        st, h, _ = self._raw("GET", "/api/health", {"Origin": "http://localhost:5173"})
        self.assertEqual(h["Access-Control-Allow-Origin"], "http://localhost:5173")
        st, h, _ = self._raw("GET", "/api/health", {"Origin": "http://evil.example"})
        self.assertIsNone(h["Access-Control-Allow-Origin"])

    def test_static_and_traversal(self):
        st, h, body = self._raw("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn(b"<div id=\"app\">", body)
        self.assertIn("text/html", h["Content-Type"])
        st, h, body = self._raw("GET", "/config.js")
        self.assertEqual(st, 200)
        self.assertIn(b"APP_CONFIG", body)
        st, h, _ = self._raw("GET", "/app.js")
        self.assertEqual(st, 200)
        self.assertEqual(h["Content-Type"], "application/javascript; charset=utf-8")
        st, h, _ = self._raw("GET", "/styles.css")
        self.assertEqual((st, h["Content-Type"]), (200, "text/css; charset=utf-8"))
        for evil in ("/../backend/app/config.py", "/%2e%2e/backend/app/config.py", "/..%2f..%2fetc/passwd",
                     "/%2e%2e%2f%2e%2e%2fetc%2fpasswd", "/nope.txt"):
            self.assertEqual(self._raw("GET", evil)[0], 404, evil)

    def test_security_headers_and_method_errors(self):
        st, h, _ = self._raw("GET", "/api/health")
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'self'", h["Content-Security-Policy"])
        self.assertEqual(self._raw("PUT", "/api/projects")[0], 405)
        self.assertEqual(self._raw("GET", "/api/nope")[0], 404)

    def test_malformed_requests_do_not_crash_server(self):
        c = self.env.client()
        self.assertEqual(c.req("POST", "/api/auth/login", raw=b"\xff\xfe", ctype="application/json")[0], 400)
        self.assertEqual(c.req("POST", "/api/auth/login", headers={"Content-Length": "abc"})[0] in (400, 411), True)
        self.assertEqual(c.get("/api/health")[0], 200)


class TestRunnerRecovery(unittest.TestCase):
    def test_stale_jobs_are_failed_on_startup(self):
        env = Env()
        try:
            c, user = env.signup("rec@example.com")
            pid = c.post("/api/projects", {"name": "P"})[1]["id"]
            with env.app.db.conn() as db:
                for jid, st in (("j-queued", "queued"), ("j-running", "running"), ("j-done", "succeeded")):
                    db.execute("INSERT INTO jobs(id,project_id,method,model_name,params_json,status,created_at) VALUES (?,?,?,?,?,?,?)",
                               (jid, pid, "tfidf-logreg", "m", "{}", st, "t"))
            from app.runner import JobRunner
            JobRunner(env.settings, env.app.db).start()  # what a restarted server does
            states = {j: c.get("/api/jobs/" + j)[1] for j in ("j-queued", "j-running", "j-done")}
            self.assertEqual([states[j]["status"] for j in states], ["failed", "failed", "succeeded"])
            self.assertIn("restarted", states["j-running"]["error"])
        finally:
            env.close()


class TestConfigAndMigrations(unittest.TestCase):
    def test_production_requires_strong_secret(self):
        with self.assertRaises(RuntimeError):
            Settings({"APP_ENV": "production"})
        with self.assertRaises(RuntimeError):
            Settings({"APP_ENV": "production", "JWT_SECRET": "short"})
        s = Settings({"APP_ENV": "production", "JWT_SECRET": "x" * 40})
        self.assertEqual(s.jwt_secret, "x" * 40)

    def test_migrations_idempotent_and_foreign_keys_cascade(self):
        import shutil
        import tempfile
        d = tempfile.mkdtemp()
        try:
            db = Database(d + "/t.db")
            self.assertEqual(migrate(db), ["001_init"])
            self.assertEqual(migrate(db), [])
            with db.conn() as c:
                c.execute("INSERT INTO users VALUES ('u','e@x.co','h','t')")
                c.execute("INSERT INTO projects VALUES ('p','u','n','','t')")
                c.execute("DELETE FROM users WHERE id='u'")
                self.assertEqual(c.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 0)
                with self.assertRaises(sqlite3.IntegrityError):
                    c.execute("INSERT INTO projects VALUES ('p2','missing','n','','t')")
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
