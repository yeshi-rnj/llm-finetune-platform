import json
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import security, trainer
from .core import ApiError

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id():
    return uuid.uuid4().hex


def _text(d, key, maxlen, required=True, default=""):
    v = d.get(key, default)
    if not isinstance(v, str):
        raise ApiError(400, "%s must be a string" % key)
    v = v.strip()
    if required and not v:
        raise ApiError(400, "%s is required" % key)
    if len(v) > maxlen:
        raise ApiError(400, "%s must be at most %d characters" % (key, maxlen))
    return v


# ------------------------------------------------------------------ ownership helpers
# Every lookup of a user-owned object joins through projects.owner_id. Foreign objects look
# exactly like missing ones (404), so ids cannot be probed.
def owned_project(c, ctx, pid):
    r = c.execute("SELECT * FROM projects WHERE id=? AND owner_id=?", (pid, ctx.user["id"])).fetchone()
    if not r:
        raise ApiError(404, "Project not found")
    return r


def owned_dataset(c, ctx, did):
    r = c.execute("SELECT d.* FROM datasets d JOIN projects p ON p.id=d.project_id WHERE d.id=? AND p.owner_id=?",
                  (did, ctx.user["id"])).fetchone()
    if not r:
        raise ApiError(404, "Dataset not found")
    return r


def owned_job(c, ctx, jid):
    r = c.execute("SELECT j.* FROM jobs j JOIN projects p ON p.id=j.project_id WHERE j.id=? AND p.owner_id=?",
                  (jid, ctx.user["id"])).fetchone()
    if not r:
        raise ApiError(404, "Job not found")
    return r


def owned_model(c, ctx, mid):
    r = c.execute("SELECT m.* FROM models m JOIN projects p ON p.id=m.project_id WHERE m.id=? AND p.owner_id=?",
                  (mid, ctx.user["id"])).fetchone()
    if not r:
        raise ApiError(404, "Model not found")
    return r


def remove_paths(ctx, paths):
    root = ctx.settings.data_dir
    for p in paths:
        try:
            path = Path(p).resolve()
            if not path.is_relative_to(root):
                continue
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink()
        except OSError:
            pass


# ------------------------------------------------------------------ serializers
def s_project(r):
    return {"id": r["id"], "name": r["name"], "description": r["description"], "created_at": r["created_at"]}


def s_dataset(r):
    return {"id": r["id"], "project_id": r["project_id"], "name": r["name"], "row_count": r["row_count"],
            "labels": json.loads(r["labels_json"]), "created_at": r["created_at"]}


def s_job(r):
    return {"id": r["id"], "project_id": r["project_id"], "dataset_id": r["dataset_id"], "method": r["method"],
            "model_name": r["model_name"], "params": json.loads(r["params_json"]), "status": r["status"],
            "error": r["error"], "metrics": json.loads(r["metrics_json"]) if r["metrics_json"] else None,
            "model_id": r["model_id"], "created_at": r["created_at"], "started_at": r["started_at"],
            "finished_at": r["finished_at"]}


def s_model(r):
    return {"id": r["id"], "project_id": r["project_id"], "job_id": r["job_id"], "name": r["name"],
            "method": r["method"], "labels": json.loads(r["labels_json"]), "created_at": r["created_at"]}


def s_eval(r):
    return {"id": r["id"], "model_id": r["model_id"], "metrics": json.loads(r["metrics_json"]), "created_at": r["created_at"]}


# ------------------------------------------------------------------ system
def health(ctx):
    with ctx.db.conn() as c:
        c.execute("SELECT 1").fetchone()
    return {"status": "ok"}


# ------------------------------------------------------------------ auth
def register(ctx):
    d = ctx.json()
    email = _text(d, "email", 254).lower()
    pw = d.get("password")
    if not EMAIL_RE.match(email):
        raise ApiError(400, "A valid email is required")
    if not isinstance(pw, str) or not (8 <= len(pw) <= 128):
        raise ApiError(400, "Password must be 8-128 characters")
    uid = new_id()
    ph = security.hash_password(pw)
    try:
        with ctx.db.conn() as c:
            c.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES (?,?,?,?)", (uid, email, ph, now()))
    except sqlite3.IntegrityError:
        raise ApiError(409, "Email already registered")
    return 201, {"token": security.make_token(uid, ctx.settings.jwt_secret, ctx.settings.jwt_ttl),
                 "user": {"id": uid, "email": email}}


def login(ctx):
    d = ctx.json()
    email = str(d.get("email", "")).strip().lower()
    pw = d.get("password")
    pw = pw if isinstance(pw, str) else ""
    with ctx.db.conn() as c:
        u = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    ok = security.verify_password(pw, u["password_hash"] if u else security.DUMMY_HASH)
    if not u or not ok:
        raise ApiError(401, "Invalid email or password")
    return {"token": security.make_token(u["id"], ctx.settings.jwt_secret, ctx.settings.jwt_ttl),
            "user": {"id": u["id"], "email": u["email"]}}


def me(ctx):
    return {"user": {"id": ctx.user["id"], "email": ctx.user["email"]}}


# ------------------------------------------------------------------ projects
def list_projects(ctx):
    with ctx.db.conn() as c:
        rows = c.execute("SELECT * FROM projects WHERE owner_id=? ORDER BY created_at DESC, rowid DESC", (ctx.user["id"],)).fetchall()
    return {"projects": [s_project(r) for r in rows]}


def create_project(ctx):
    d = ctx.json()
    name = _text(d, "name", 100)
    desc = _text(d, "description", 1000, required=False)
    pid = new_id()
    with ctx.db.conn() as c:
        c.execute("INSERT INTO projects(id,owner_id,name,description,created_at) VALUES (?,?,?,?,?)",
                  (pid, ctx.user["id"], name, desc, now()))
        r = c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    return 201, s_project(r)


def get_project(ctx):
    with ctx.db.conn() as c:
        return s_project(owned_project(c, ctx, ctx.params["pid"]))


def delete_project(ctx):
    with ctx.db.conn() as c:
        p = owned_project(c, ctx, ctx.params["pid"])
        paths = [r[0] for r in c.execute("SELECT file_path FROM datasets WHERE project_id=?", (p["id"],))]
        for r in c.execute("SELECT artifact_path, test_path FROM models WHERE project_id=?", (p["id"],)):
            paths += [r[0], r[1]]
        c.execute("DELETE FROM projects WHERE id=?", (p["id"],))
    remove_paths(ctx, paths)
    return {"deleted": True}


# ------------------------------------------------------------------ datasets
def list_datasets(ctx):
    with ctx.db.conn() as c:
        p = owned_project(c, ctx, ctx.params["pid"])
        rows = c.execute("SELECT * FROM datasets WHERE project_id=? ORDER BY created_at DESC, rowid DESC", (p["id"],)).fetchall()
    return {"datasets": [s_dataset(r) for r in rows]}


def upload_dataset(ctx):
    with ctx.db.conn() as c:
        p = owned_project(c, ctx, ctx.params["pid"])
    name = (ctx.query.get("name") or "dataset.csv").strip()[:200] or "dataset.csv"
    raw = ctx.body(ctx.settings.max_upload)
    if not raw:
        raise ApiError(400, "Empty upload")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ApiError(400, "File must be UTF-8 encoded text")
    try:
        rows, counts = trainer.parse_dataset(text)
    except trainer.DatasetError as e:
        raise ApiError(400, str(e))
    did = new_id()
    path = ctx.settings.datasets_dir / (did + ".csv")
    path.write_bytes(raw)
    try:
        with ctx.db.conn() as c:
            c.execute("INSERT INTO datasets(id,project_id,name,row_count,labels_json,file_path,created_at) VALUES (?,?,?,?,?,?,?)",
                      (did, p["id"], name, len(rows), json.dumps(counts), str(path), now()))
            r = c.execute("SELECT * FROM datasets WHERE id=?", (did,)).fetchone()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return 201, s_dataset(r)


def get_dataset(ctx):
    with ctx.db.conn() as c:
        r = owned_dataset(c, ctx, ctx.params["id"])
    out = s_dataset(r)
    try:
        rows, _ = trainer.parse_dataset(Path(r["file_path"]).read_text(encoding="utf-8-sig"))
        out["preview"] = [{"text": t[:300], "label": lab} for t, lab in rows[:10]]
    except (OSError, trainer.DatasetError):
        out["preview"] = []
    return out


def delete_dataset(ctx):
    with ctx.db.conn() as c:
        r = owned_dataset(c, ctx, ctx.params["id"])
        c.execute("DELETE FROM datasets WHERE id=?", (r["id"],))
    remove_paths(ctx, [r["file_path"]])
    return {"deleted": True}


# ------------------------------------------------------------------ jobs
def list_jobs(ctx):
    with ctx.db.conn() as c:
        p = owned_project(c, ctx, ctx.params["pid"])
        rows = c.execute("SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC, rowid DESC", (p["id"],)).fetchall()
    return {"jobs": [s_job(r) for r in rows]}


def create_job(ctx):
    d = ctx.json()
    method = d.get("method", "tfidf-logreg")
    raw_params = d.get("params")
    try:
        params = trainer.validate_params(method, {} if raw_params is None else raw_params)
    except ValueError as e:
        raise ApiError(400, str(e))
    name = _text(d, "model_name", 100, required=False)
    did = d.get("dataset_id")
    if not isinstance(did, str) or not did:
        raise ApiError(400, "dataset_id is required")
    jid = new_id()
    with ctx.db.conn() as c:
        p = owned_project(c, ctx, ctx.params["pid"])
        ds = c.execute("SELECT * FROM datasets WHERE id=? AND project_id=?", (did, p["id"])).fetchone()
        if not ds:
            raise ApiError(404, "Dataset not found in this project")
        name = name or "%s-%s" % (method, jid[:6])
        c.execute("INSERT INTO jobs(id,project_id,dataset_id,method,model_name,params_json,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
                  (jid, p["id"], ds["id"], method, name, json.dumps(params), "queued", now()))
        r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    ctx.runner.submit(jid)
    return 201, s_job(r)


def get_job(ctx):
    with ctx.db.conn() as c:
        return s_job(owned_job(c, ctx, ctx.params["id"]))


# ------------------------------------------------------------------ models
def list_models(ctx):
    with ctx.db.conn() as c:
        p = owned_project(c, ctx, ctx.params["pid"])
        rows = c.execute("SELECT * FROM models WHERE project_id=? ORDER BY created_at DESC, rowid DESC", (p["id"],)).fetchall()
    return {"models": [s_model(r) for r in rows]}


def get_model(ctx):
    with ctx.db.conn() as c:
        return s_model(owned_model(c, ctx, ctx.params["id"]))


def delete_model(ctx):
    with ctx.db.conn() as c:
        m = owned_model(c, ctx, ctx.params["id"])
        c.execute("DELETE FROM models WHERE id=?", (m["id"],))
        c.execute("UPDATE jobs SET model_id=NULL WHERE model_id=?", (m["id"],))
    remove_paths(ctx, [m["artifact_path"], m["test_path"]])
    return {"deleted": True}


def evaluate_model(ctx):
    with ctx.db.conn() as c:
        m = owned_model(c, ctx, ctx.params["id"])
    try:
        metrics = trainer.evaluate(m["method"], m["artifact_path"], m["test_path"])
    except (OSError, trainer.TrainingError) as e:
        raise ApiError(500, "Evaluation failed: %s" % e)
    eid = new_id()
    with ctx.db.conn() as c:
        c.execute("INSERT INTO evaluations(id,model_id,metrics_json,created_at) VALUES (?,?,?,?)",
                  (eid, m["id"], json.dumps(metrics), now()))
        r = c.execute("SELECT * FROM evaluations WHERE id=?", (eid,)).fetchone()
    return 201, s_eval(r)


def list_evaluations(ctx):
    with ctx.db.conn() as c:
        m = owned_model(c, ctx, ctx.params["id"])
        rows = c.execute("SELECT * FROM evaluations WHERE model_id=? ORDER BY created_at DESC, rowid DESC", (m["id"],)).fetchall()
    return {"evaluations": [s_eval(r) for r in rows]}


def predict(ctx):
    d = ctx.json()
    texts = d.get("texts")
    if not isinstance(texts, list) or not (1 <= len(texts) <= 100) or not all(isinstance(t, str) and 0 < len(t.strip()) <= 10000 for t in texts):
        raise ApiError(400, "texts must be a list of 1-100 non-empty strings (max 10000 chars each)")
    with ctx.db.conn() as c:
        m = owned_model(c, ctx, ctx.params["id"])
    try:
        preds = trainer.predict(m["method"], m["artifact_path"], [t.strip() for t in texts])
    except (OSError, trainer.TrainingError) as e:
        raise ApiError(500, "Inference failed: %s" % e)
    return {"model_id": m["id"], "predictions": preds}


def register_routes(r):
    r.add("GET", "/api/health", health, auth=False)
    r.add("POST", "/api/auth/register", register, auth=False)
    r.add("POST", "/api/auth/login", login, auth=False)
    r.add("GET", "/api/auth/me", me)
    r.add("GET", "/api/projects", list_projects)
    r.add("POST", "/api/projects", create_project)
    r.add("GET", "/api/projects/{pid}", get_project)
    r.add("DELETE", "/api/projects/{pid}", delete_project)
    r.add("GET", "/api/projects/{pid}/datasets", list_datasets)
    r.add("POST", "/api/projects/{pid}/datasets", upload_dataset)
    r.add("GET", "/api/datasets/{id}", get_dataset)
    r.add("DELETE", "/api/datasets/{id}", delete_dataset)
    r.add("GET", "/api/projects/{pid}/jobs", list_jobs)
    r.add("POST", "/api/projects/{pid}/jobs", create_job)
    r.add("GET", "/api/jobs/{id}", get_job)
    r.add("GET", "/api/projects/{pid}/models", list_models)
    r.add("GET", "/api/models/{id}", get_model)
    r.add("DELETE", "/api/models/{id}", delete_model)
    r.add("POST", "/api/models/{id}/evaluate", evaluate_model)
    r.add("GET", "/api/models/{id}/evaluations", list_evaluations)
    r.add("POST", "/api/models/{id}/predict", predict)
