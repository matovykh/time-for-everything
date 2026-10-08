"""Regression tests for tests/security/scan_secrets.py (stdlib unittest; fake canary values only).

Run: python3 -I -m unittest discover -s tests/security -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import scan_secrets  # noqa: E402

FAKE_KEY = "sk-proj-" + "Q" * 32
FAKE_PW = "S3cr3t" + "Value99"


def run_on(files: dict[str, str]) -> list[tuple]:
    with tempfile.TemporaryDirectory() as d:
        for rel, content in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        return scan_secrets.scan([Path(d)])


def labels(findings):
    return sorted(f[1] for f in findings)


class FalsePositivesStayQuiet(unittest.TestCase):
    def test_empty_env_example_values_do_not_swallow_next_line(self):
        f = run_on({"backend/.env.example": "DATABASE_URL=\nDB_POOL_SIZE=5\nOPENAI_API_KEY=\nOPENAI_MODEL=\n"})
        self.assertEqual(f, [])

    def test_placeholder_values(self):
        f = run_on({".env.example": "SESSION_SECRET=<generate-64-random-bytes>\nOPENAI_API_KEY=changeme\n"})
        self.assertEqual(f, [])

    def test_variable_names_in_client_error_fixture(self):
        src = 'apiError(503, "service_not_configured", { details: { missing: ["DATABASE_URL", "SUPABASE_URL"] } })\n'
        self.assertEqual(run_on({"frontend/src/test/screens.test.tsx": src}), [])


class RealLeaksStillCaught(unittest.TestCase):
    def test_env_assignments(self):
        f = run_on({"backend/.env.example": f"DATABASE_URL=postgresql://app:{FAKE_PW}@db.x.supabase.co:5432/p\n"
                                            f"OPENAI_API_KEY={FAKE_KEY}\nSESSION_SECRET={FAKE_PW}\n"})
        self.assertIn("assigned_secret_value", labels(f))
        self.assertIn("openai_key", labels(f))
        self.assertIn("postgres_dsn_with_password", labels(f))
        self.assertGreaterEqual(labels(f).count("assigned_secret_value"), 3)

    def test_yaml_style_assignment(self):
        f = run_on({".github/workflows/deploy.yml": f"    DATABASE_URL: postgresql://u:{FAKE_PW}@prod.example:5432/db\n"})
        self.assertIn("assigned_secret_value", labels(f))
        self.assertIn("postgres_dsn_with_password", labels(f))

    def test_client_env_access_and_vite_secret(self):
        f = run_on({"frontend/src/x.ts": "const k = import.meta.env.VITE_OPENAI_KEY;\nprocess.env.DATABASE_URL\n"})
        self.assertIn("secret_exposed_via_vite_env", labels(f))
        self.assertIn("server_env_in_client", labels(f))

    def test_token_in_web_storage(self):
        f = run_on({"frontend/src/s.ts": 'localStorage.setItem("access_token", t)\n'})
        self.assertIn("token_in_web_storage", labels(f))

    def test_allowlist_is_exact_and_path_bound(self):
        line = "          TEST_DATABASE_URL: postgresql://postgres:local-ci-only@127.0.0.1:5432/tfe_test\n"
        self.assertEqual(run_on({".github/workflows/ci.yml": line}), [])
        # same text in a different file -> reported
        self.assertIn("postgres_dsn_with_password", labels(run_on({".github/workflows/other.yml": line})))
        # different password in the allowlisted file -> reported
        other = line.replace("local-ci-only", FAKE_PW)
        self.assertIn("postgres_dsn_with_password", labels(run_on({".github/workflows/ci.yml": other})))
        # non-loopback host in the allowlisted file -> reported
        remote = line.replace("127.0.0.1", "db.example.com")
        self.assertIn("postgres_dsn_with_password", labels(run_on({".github/workflows/ci.yml": remote})))


if __name__ == "__main__":
    unittest.main()
