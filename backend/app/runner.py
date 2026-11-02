import json
import logging
import queue
import threading
import uuid
from datetime import datetime, timezone

from . import trainer

log = logging.getLogger("runner")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobRunner:
    """Single background worker thread. Jobs live in SQLite; the queue is in-memory.

    On startup, jobs left queued/running by a previous process are marked failed (no resume).
    """

    def __init__(self, settings, db):
        self.settings = settings
        self.db = db
        self.q = queue.Queue()
        self.thread = threading.Thread(target=self._loop, name="job-runner", daemon=True)

    def start(self):
        with self.db.conn() as c:
            c.execute("UPDATE jobs SET status='failed', error='Server restarted before the job finished', finished_at=? "
                      "WHERE status IN ('queued','running')", (now(),))
        self.thread.start()

    def submit(self, job_id):
        self.q.put(job_id)

    def _loop(self):
        while True:
            job_id = self.q.get()
            try:
                self._run(job_id)
            except Exception:  # never let the worker die
                log.exception("job %s crashed the runner", job_id)
            finally:
                self.q.task_done()

    def _run(self, job_id):
        with self.db.conn() as c:
            job = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                return
            c.execute("UPDATE jobs SET status='running', started_at=? WHERE id=?", (now(), job_id))
            ds = c.execute("SELECT file_path FROM datasets WHERE id=?", (job["dataset_id"],)).fetchone() if job["dataset_id"] else None
        try:
            if not ds:
                raise trainer.TrainingError("Dataset no longer exists")
            with open(ds["file_path"], encoding="utf-8-sig") as f:
                rows, _ = trainer.parse_dataset(f.read())
            model_id = uuid.uuid4().hex
            res = trainer.run_training(job["method"], rows, json.loads(job["params_json"]), model_id, self.settings.models_dir)
        except Exception as e:
            log.warning("job %s failed: %s", job_id, e)
            msg = (str(e) or e.__class__.__name__)[:500]
            with self.db.conn() as c:
                c.execute("UPDATE jobs SET status='failed', error=?, finished_at=? WHERE id=?", (msg, now(), job_id))
            return
        with self.db.conn() as c:
            c.execute("INSERT INTO models(id,project_id,job_id,name,method,labels_json,artifact_path,test_path,created_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?)",
                      (model_id, job["project_id"], job_id, job["model_name"], job["method"], json.dumps(res["labels"]),
                       str(res["artifact"]), str(res["test_path"]), now()))
            c.execute("UPDATE jobs SET status='succeeded', metrics_json=?, model_id=?, finished_at=? WHERE id=?",
                      (json.dumps(res["metrics"]), model_id, now(), job_id))
