"""Fail if likely secrets are present in files git tracks (or would track). Usage: python scripts/scan_secrets.py"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "HuggingFace token": re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),
    "Anthropic/OpenAI key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{30,}\b"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "hard-coded credential": re.compile(r"""(?i)\b(?:secret|passwd|password|api[_-]?key|token)\w*\s*[=:]\s*["'][^"'\s]{16,}["']"""),
}
ALLOW_FILES = {".env.example"}


SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "data"}


def candidate_files():
    try:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True)
        return [ROOT / f for f in out.stdout.splitlines() if f]
    except (subprocess.CalledProcessError, FileNotFoundError):  # not a git repo / git missing: walk the tree
        return [f for f in ROOT.rglob("*") if f.is_file() and not SKIP_DIRS & set(f.relative_to(ROOT).parts)]


def main():
    problems = []
    files = candidate_files()
    names = {f.name for f in files}
    for bad in (".env", "app.db"):
        if bad in names:
            problems.append("%s would be committed" % bad)
    for f in files:
        if f.name in ALLOW_FILES or f.suffix in {".png", ".ico", ".zip", ".joblib", ".db"}:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for label, rx in PATTERNS.items():
                if rx.search(line):
                    problems.append("%s:%d: possible %s" % (f.relative_to(ROOT), i, label))
    # .env.example must hold no real value
    ex = ROOT / ".env.example"
    if ex.exists():
        for line in ex.read_text().splitlines():
            if line.startswith("JWT_SECRET=") and line.strip() != "JWT_SECRET=":
                problems.append(".env.example must leave JWT_SECRET empty")
    print("Scanned %d files." % len(files))
    if problems:
        print("\n".join("PROBLEM: " + p for p in problems))
        sys.exit(1)
    print("No secrets found.")


main()
