"""Static guards for the deploy files (no Docker needed)."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TestDeployConfig(unittest.TestCase):
    def test_compose_forces_production_and_requires_secret(self):
        c = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("APP_ENV: production", c)
        self.assertIn("JWT_SECRET: ${JWT_SECRET:?", c)
        self.assertIn("127.0.0.1", c)

    def test_dockerfile_uses_pinned_lock_file(self):
        d = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("requirements.lock", d)
        self.assertTrue((ROOT / "backend" / "requirements.lock").is_file())
        for line in (ROOT / "backend" / "requirements.lock").read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                self.assertIn("==", line, "unpinned: " + line)

    def test_env_example_has_empty_secret(self):
        self.assertIn("\nJWT_SECRET=\n", (ROOT / ".env.example").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
