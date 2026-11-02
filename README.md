# LLM Fine-Tuning Platform

A multi-user web application that allows users to create projects, upload labeled datasets, train machine learning models, evaluate model performance, manage trained models, and run predictions through a simple web interface.

🌐 **Live Demo:** https://llm-finetune-platform.onrender.com

## 🚀 Features

- **User Authentication** – Sign up and log in securely.
- **Project Management** – Create and manage multiple ML projects.
- **Dataset Upload** – Upload labeled CSV datasets.
- **Model Training** – Train models using supported training methods.
- **Model Registry** – Browse and manage trained models.
- **Model Evaluation** – Evaluate models on a held-out dataset split.
- **Inference** – Run predictions using trained models.

## 🛠️ Tech Stack

| Component | Technologies |
|---|---|
| Backend | Python 3.10+, Standard Library HTTP Server |
| Frontend | HTML, CSS, JavaScript |
| Database | SQLite |
| Machine Learning | Scikit-learn |
| Authentication | PyJWT |
| Deployment | Docker, Render |

## 🧠 Training Methods

### 1. TF-IDF + Logistic Regression (`tfidf-logreg`)
- Converts text into numerical features using TF-IDF.
- Uses Logistic Regression for classification.
- Runs on CPU.
- Tested successfully.

### 2. LoRA Fine-Tuning (`lora-causal-lm`)
- Uses Hugging Face Transformers and PEFT.
- Supports LoRA-based fine-tuning.
- Requires additional dependencies such as PyTorch, Transformers, and PEFT.
- Realistically requires GPU resources.
- Not tested end-to-end.

## 📂 Dataset Format

Upload a CSV file with the following structure:

| text | label |
|---|---|
| This product is excellent | positive |
| Very disappointing experience | negative |
| I really liked this product | positive |
| The service was terrible | negative |

**Dataset requirements:**
- CSV format with UTF-8 encoding.
- Header row must contain `text` and `label`.
- Minimum 10 rows.
- At least 2 different labels.
- At least 2 rows per label.

## 💻 Run Locally

### Prerequisites
- Python 3.10 or later
- Git
- Windows PowerShell

### Setup

```powershell
git clone https://github.com/yeshi-rnj/llm-finetune-platform.git
cd llm-finetune-platform

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\scripts\setup.ps1
.\scripts\run.ps1
```

Open the application:

```text
http://127.0.0.1:8000
```

Run tests:

```powershell
.\scripts\test.ps1
```

## ☁️ Deployment

The application is deployed using **Docker on Render**.

**Live Application:** https://llm-finetune-platform.onrender.com

### Deployment Configuration

- Platform: Render
- Deployment method: Docker
- Dockerfile: `Dockerfile`
- Build context: Repository root (`.`)
- Application port: `10000`
- Runtime environment: Production

### Environment Variables

Configure the following variables in your Render service:

| Variable | Description |
|---|---|
| `APP_ENV` | Set to `production` |
| `JWT_SECRET` | Secure secret of at least 32 characters |
| `DATA_DIR` | Application data directory, configured as `/data` |
| `HOST` | `0.0.0.0` |
| `PORT` | `10000` |

**Important:** Never commit your `.env` file or expose your JWT secret in a public repository.

### Persistent Storage

The application uses SQLite and local storage for datasets and model artifacts.

For production use, configure a Render persistent disk mounted at:

```text
/data
```

Without persistent storage, application data may be lost when the service restarts or is redeployed.

### Free Instance Note

The Render free instance may spin down after inactivity. The first request after inactivity can take around 50 seconds or longer.

## ⚙️ Configuration

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | Application environment |
| `JWT_SECRET` | Development-only value | Authentication secret |
| `DATA_DIR` | `./data` | Database and artifact storage |
| `HOST` | `127.0.0.1` | Server bind address |
| `PORT` | `8000` | Server port |
| `CORS_ORIGINS` | Empty | Allowed cross-origin origins |
| `API_BASE_URL` | Empty | API URL for separate frontend hosting |
| `MAX_UPLOAD_BYTES` | 10 MiB | Maximum upload size |

## ⚠️ Known Limitations

- One server process and one training worker.
- Jobs queued or running during a restart are marked as failed; they cannot resume automatically.
- No login rate limiting.
- No email verification or password reset.
- SQLite and local disk storage are not horizontally scalable.
- LoRA training has not been tested end-to-end.
- Model artifacts are stored as `.joblib` pickles and must only be loaded by the trusted server.

## 🔮 Future Improvements

- PostgreSQL database integration.
- Cloud-based object storage for datasets and models.
- Background job processing with a dedicated queue.
- GPU-enabled model fine-tuning.
- Improved authentication and security.
- Training progress monitoring and visualization.

## 👩‍💻 Author

**Yeshashvi Ranjan**

GitHub: https://github.com/yeshi-rnj

---

⭐ If you find this project interesting, consider giving the repository a star!
