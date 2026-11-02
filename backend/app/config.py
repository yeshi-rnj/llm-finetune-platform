import os
from pathlib import Path

_DEV_SECRET = "dev-only-insecure-secret-do-not-use-in-production"


class Settings:
    def __init__(self, env=None):
        e = (env if env is not None else os.environ).get
        self.env = e("APP_ENV", "development")
        self.data_dir = Path(e("DATA_DIR", "./data")).resolve()
        self.db_path = Path(e("DATABASE_PATH", str(self.data_dir / "app.db"))).resolve()
        self.jwt_secret = e("JWT_SECRET", "")
        self.jwt_ttl = int(e("JWT_TTL_SECONDS", "86400"))
        self.cors_origins = [o.strip() for o in e("CORS_ORIGINS", "").split(",") if o.strip()]
        self.max_upload = int(e("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
        self.host = e("HOST", "127.0.0.1")
        self.port = int(e("PORT", "8000"))
        self.api_base_url = e("API_BASE_URL", "").rstrip("/")
        default_fe = Path(__file__).resolve().parents[2] / "frontend"
        self.frontend_dir = Path(e("FRONTEND_DIR", str(default_fe))).resolve()
        self.log_requests = e("LOG_REQUESTS", "1") == "1"
        if not self.jwt_secret:
            if self.env == "production":
                raise RuntimeError("JWT_SECRET must be set when APP_ENV=production")
            self.jwt_secret = _DEV_SECRET
        elif self.env == "production" and len(self.jwt_secret) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 characters in production")
        self.datasets_dir = self.data_dir / "datasets"
        self.models_dir = self.data_dir / "models"

    def ensure_dirs(self):
        for d in (self.data_dir, self.datasets_dir, self.models_dir, self.db_path.parent):
            d.mkdir(parents=True, exist_ok=True)
