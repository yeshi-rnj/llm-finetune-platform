# LLM Fine-Tuning Platform

A small multi-user web app: sign up → create projects → upload labeled CSV datasets → submit training jobs →
browse a model registry → evaluate on a held-out split → run inference.

* **Backend** – Python 3.10+ standard-library HTTP server, SQLite (with SQL migrations), PyJWT, scikit-learn.
* **Frontend** – dependency-free JavaScript SPA served by the backend (strict CSP, no build step).
* **Training methods**
  * `tfidf-logreg` – TF-IDF + logistic regression. Runs on CPU anywhere. **Tested.**
  * `lora-causal-lm` – LoRA fine-tuning of a Hugging Face sequence-classification model with PEFT.
    Needs `torch`, `transformers`, `peft` (`backend/requirements-lora.txt`) and, realistically, a GPU.
    **Not tested end-to-end** (see "Verification status").

## Dataset format
CSV, UTF-8, header row with `text` and `label` columns, ≥10 rows, ≥2 labels, ≥2 rows per label.

## Run locally (Windows PowerShell)
```powershell
cd llm-finetune-platform
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass   # only for this PowerShell window
.\scripts\setup.ps1      # venv, deps, .env with a generated JWT_SECRET, DB migrations
.\scripts\run.ps1        # http://127.0.0.1:8000
.\scripts\test.ps1       # backend tests + secret scan + frontend syntax check
```

## Configuration (environment variables / `.env`)
| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` | `production` makes `JWT_SECRET` mandatory (≥32 chars) |
| `JWT_SECRET` | dev-only value | **required in production** |
| `DATA_DIR` | `./data` | SQLite DB, datasets, model artifacts |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | |
| `CORS_ORIGINS` | empty | comma-separated; only needed if the UI is on another origin |
| `API_BASE_URL` | empty | only if the UI is on another origin than the API |
| `MAX_UPLOAD_BYTES` | 10 MiB | |

## Deploy
Single container, one instance, one persistent volume (SQLite + job queue are in-process):
```bash
cp .env.example .env     # set JWT_SECRET (python -c "import secrets; print(secrets.token_urlsafe(48))")
docker compose up -d --build
```
Compose forces `APP_ENV=production` and refuses to start unless `JWT_SECRET` (>= 32 chars) is set in `.env`.
The port is published on `127.0.0.1` only; put a TLS-terminating reverse proxy (Caddy, nginx, a cloud load balancer) in
front – the app speaks plain HTTP – or set `BIND_ADDR=0.0.0.0` in `.env` to expose it directly (not recommended without TLS).
The image installs exact versions from `backend/requirements.lock`; re-test before bumping them, because saved models are
pickles tied to the scikit-learn version. Back up the `appdata` volume.
For GPU/LoRA: set `INSTALL_LORA=1` in `.env` and build on a CUDA base image. Hugging Face downloads are cached in `/data/hf`.

## Known limitations
* One server process / one training worker; jobs queued or running at restart are marked failed (no resume).
* No login rate-limiting, e-mail verification, password reset or token revocation.
* SQLite + local disk: not horizontally scalable. Move to Postgres + object storage + a real queue for that.
* Model artifacts (`.joblib`) are pickles written and read only by the server; never import artifacts from untrusted sources.
