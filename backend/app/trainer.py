"""Training / evaluation / inference.

Methods
  tfidf-logreg    : TF-IDF + logistic regression text classifier (scikit-learn). CPU, runs anywhere.
  lora-causal-lm  : name kept for API stability; LoRA fine-tunes a Hugging Face *sequence classification*
                    model with PEFT. Needs torch + transformers + peft (+ GPU for non-toy models).
                    NOT exercised by the automated tests in a CPU-only/no-network sandbox.
"""
import csv
import io
import json
import math
import random
import re
from collections import Counter
from pathlib import Path

MAX_ROWS = 100_000
METHODS = ("tfidf-logreg", "lora-causal-lm")


class DatasetError(ValueError):
    pass


class TrainingError(RuntimeError):
    pass


def parse_dataset(text):
    reader = csv.DictReader(io.StringIO(text))
    fields = [(f or "").strip().lower() for f in (reader.fieldnames or [])]
    if "text" not in fields or "label" not in fields:
        raise DatasetError("CSV must have a header row with 'text' and 'label' columns")
    reader.fieldnames = fields
    rows = []
    try:
        for r in reader:
            t = (r.get("text") or "").strip()
            lab = (r.get("label") or "").strip()
            if t and lab:
                rows.append((t[:20000], lab[:100]))
                if len(rows) > MAX_ROWS:
                    raise DatasetError("Dataset exceeds %d rows" % MAX_ROWS)
    except csv.Error as e:
        raise DatasetError("Malformed CSV: %s" % e)
    counts = Counter(lab for _, lab in rows)
    if len(rows) < 10:
        raise DatasetError("Dataset needs at least 10 valid rows (found %d)" % len(rows))
    if len(counts) < 2:
        raise DatasetError("Dataset needs at least 2 distinct labels")
    if len(counts) > 50:
        raise DatasetError("Dataset has more than 50 distinct labels")
    if min(counts.values()) < 2:
        raise DatasetError("Every label needs at least 2 rows")
    return rows, dict(counts)


def _num(p, key, default, lo, hi, cast):
    v = p.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("%s must be a number" % key)
    v = cast(v)
    if not (lo <= v <= hi) or (isinstance(v, float) and math.isnan(v)):
        raise ValueError("%s must be between %s and %s" % (key, lo, hi))
    return v


_BASE_RE = re.compile(r"^[A-Za-z0-9][\w.\-]{0,60}(/[\w.\-]{1,60})?$")


def validate_params(method, p):
    if method not in METHODS:
        raise ValueError("method must be one of: %s" % ", ".join(METHODS))
    if not isinstance(p, dict):
        raise ValueError("params must be an object")
    if method == "tfidf-logreg":
        allowed = {"C", "max_features", "ngram_max", "test_size"}
    else:
        allowed = {"base_model", "epochs", "learning_rate", "lora_r", "test_size", "max_length"}
    extra = set(p) - allowed
    if extra:
        raise ValueError("Unknown params: %s" % ", ".join(sorted(extra)))
    out = {"test_size": _num(p, "test_size", 0.2, 0.1, 0.5, float)}
    if method == "tfidf-logreg":
        out["C"] = _num(p, "C", 1.0, 0.001, 1000, float)
        out["max_features"] = _num(p, "max_features", 20000, 100, 200000, int)
        out["ngram_max"] = _num(p, "ngram_max", 2, 1, 3, int)
    else:
        bm = p.get("base_model", "distilbert-base-uncased")
        if not isinstance(bm, str) or not _BASE_RE.match(bm) or ".." in bm:
            raise ValueError("base_model must be a Hugging Face model id like 'org/name'")
        out["base_model"] = bm
        out["epochs"] = _num(p, "epochs", 3, 1, 10, int)
        out["learning_rate"] = _num(p, "learning_rate", 2e-4, 1e-6, 1e-2, float)
        out["lora_r"] = _num(p, "lora_r", 8, 1, 64, int)
        out["max_length"] = _num(p, "max_length", 128, 16, 512, int)
    return out


def _split(rows, test_size):
    from sklearn.model_selection import train_test_split
    labels = [lab for _, lab in rows]
    try:
        return train_test_split(rows, test_size=test_size, random_state=42, stratify=labels)
    except ValueError:
        return train_test_split(rows, test_size=test_size, random_state=42)


def compute_metrics(y_true, y_pred, labels):
    from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support
    p, r, f, s = precision_recall_fscore_support(y_true, y_pred, labels=labels, zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    return {
        "n": len(y_true),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "macro_f1": round(float(f.mean()), 4),
        "per_class": [
            {"label": lab, "precision": round(float(p[i]), 4), "recall": round(float(r[i]), 4),
             "f1": round(float(f[i]), 4), "support": int(s[i])}
            for i, lab in enumerate(labels)
        ],
        "confusion_matrix": {"labels": labels, "matrix": cm.tolist()},
    }


# ---------------------------------------------------------------- tfidf-logreg
def _train_tfidf(rows, params, model_id, models_dir):
    import joblib
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    train, test = _split(rows, params["test_size"])
    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(max_features=params["max_features"], ngram_range=(1, params["ngram_max"]), sublinear_tf=True)),
        ("clf", LogisticRegression(C=params["C"], max_iter=1000)),
    ])
    pipe.fit([t for t, _ in train], [lab for _, lab in train])
    labels = [str(c) for c in pipe.classes_]
    artifact = Path(models_dir) / (model_id + ".joblib")
    test_path = Path(models_dir) / (model_id + ".test.json")
    joblib.dump(pipe, artifact)
    test_path.write_text(json.dumps(test), encoding="utf-8")
    pred = pipe.predict([t for t, _ in test])
    return {"artifact": artifact, "test_path": test_path, "labels": labels,
            "metrics": compute_metrics([lab for _, lab in test], list(pred), labels)}


def _predict_tfidf(artifact, texts):
    import joblib
    pipe = joblib.load(artifact)
    probs = pipe.predict_proba(texts)
    classes = [str(c) for c in pipe.classes_]
    out = []
    for row in probs:
        i = int(row.argmax())
        out.append({"label": classes[i], "confidence": round(float(row[i]), 4),
                    "probabilities": {c: round(float(x), 4) for c, x in zip(classes, row)}})
    return out


# ---------------------------------------------------------------- LoRA (optional, untested here)
def _require_lora():
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        import peft  # noqa: F401
    except ImportError as e:
        raise TrainingError(
            "LoRA fine-tuning requires torch, transformers and peft (pip install -r backend/requirements-lora.txt). "
            "Missing module: %s" % e.name)
    import torch
    return torch


def _lora_probs(model, tok, texts, max_length, device, torch):
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(texts), 16):
            enc = tok(texts[i:i + 16], truncation=True, max_length=max_length, padding=True, return_tensors="pt").to(device)
            out.extend(torch.softmax(model(**enc).logits, dim=-1).cpu().tolist())
    return out


def _train_lora(rows, params, model_id, models_dir):
    torch = _require_lora()
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    labels = sorted({lab for _, lab in rows})
    l2i = {lab: i for i, lab in enumerate(labels)}
    train, test = _split(rows, params["test_size"])
    tok = AutoTokenizer.from_pretrained(params["base_model"])
    model = AutoModelForSequenceClassification.from_pretrained(
        params["base_model"], num_labels=len(labels), id2label=dict(enumerate(labels)), label2id=l2i)
    model = get_peft_model(model, LoraConfig(task_type=TaskType.SEQ_CLS, r=params["lora_r"],
                                             lora_alpha=2 * params["lora_r"], lora_dropout=0.05))
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=params["learning_rate"])
    bs = 16
    for epoch in range(params["epochs"]):
        model.train()
        order = random.Random(epoch).sample(range(len(train)), len(train))
        for i in range(0, len(order), bs):
            batch = [train[j] for j in order[i:i + bs]]
            enc = tok([t for t, _ in batch], truncation=True, max_length=params["max_length"],
                      padding=True, return_tensors="pt").to(device)
            y = torch.tensor([l2i[lab] for _, lab in batch], device=device)
            loss = model(**enc, labels=y).loss
            loss.backward()
            opt.step()
            opt.zero_grad()
    out_dir = Path(models_dir) / model_id
    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)
    (out_dir / "meta.json").write_text(json.dumps(
        {"base_model": params["base_model"], "labels": labels, "max_length": params["max_length"]}), encoding="utf-8")
    test_path = out_dir / "test.json"
    test_path.write_text(json.dumps(test), encoding="utf-8")
    probs = _lora_probs(model, tok, [t for t, _ in test], params["max_length"], device, torch)
    pred = [labels[max(range(len(p)), key=p.__getitem__)] for p in probs]
    return {"artifact": out_dir, "test_path": test_path, "labels": labels,
            "metrics": compute_metrics([lab for _, lab in test], pred, labels)}


def _predict_lora(artifact, texts):
    torch = _require_lora()
    from peft import PeftModel
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    meta = json.loads((Path(artifact) / "meta.json").read_text(encoding="utf-8"))
    tok = AutoTokenizer.from_pretrained(artifact)
    base = AutoModelForSequenceClassification.from_pretrained(meta["base_model"], num_labels=len(meta["labels"]))
    model = PeftModel.from_pretrained(base, artifact)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    probs = _lora_probs(model, tok, texts, meta["max_length"], device, torch)
    labels = meta["labels"]
    out = []
    for row in probs:
        i = max(range(len(row)), key=row.__getitem__)
        out.append({"label": labels[i], "confidence": round(row[i], 4),
                    "probabilities": {c: round(x, 4) for c, x in zip(labels, row)}})
    return out


# ---------------------------------------------------------------- public API
def run_training(method, rows, params, model_id, models_dir):
    if method == "tfidf-logreg":
        return _train_tfidf(rows, params, model_id, models_dir)
    if method == "lora-causal-lm":
        return _train_lora(rows, params, model_id, models_dir)
    raise TrainingError("Unknown method %s" % method)


def predict(method, artifact, texts):
    return _predict_tfidf(artifact, texts) if method == "tfidf-logreg" else _predict_lora(artifact, texts)


def evaluate(method, artifact, test_path):
    test = json.loads(Path(test_path).read_text(encoding="utf-8"))
    preds = predict(method, artifact, [t for t, _ in test])
    labels = sorted(preds[0]["probabilities"]) if preds else []
    return compute_metrics([lab for _, lab in test], [p["label"] for p in preds], labels)
