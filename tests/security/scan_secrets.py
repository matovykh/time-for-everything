#!/usr/bin/env python3
"""QA static leak scan (SPECIFICATION §10, §11, §14 "ключи не встречаются в bundle").

Stdlib only. Scans the repo (or given paths) for:
  * hard-coded secret material (OpenAI keys, JWTs, Postgres DSNs with passwords,
    Supabase service-role references in client code, SESSION_SECRET values);
  * client-side token persistence (localStorage/sessionStorage + token/jwt/refresh);
  * real .env files in the tree and Docker build context not excluding .env.

Usage:
  python3 -I tests/security/scan_secrets.py            # whole repo, default excludes
  python3 -I tests/security/scan_secrets.py frontend/dist
Exit code 1 if any HIGH finding. Prints file:line for every finding; never prints
the full matched secret (only a redacted prefix).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__", ".pytest_cache", "art", "logos", ".mypy_cache",
             # Separate DevOps repository, only temporarily nested in this workspace (git-ignored here).
             "time-for-everything_deploy"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".woff", ".woff2", ".ico", ".svg", ".map", ".lock", ".pdf"}
# QA's own test files intentionally contain fake secret-shaped canaries.
SELF_EXCLUDE = {Path("tests")}

HIGH = [
    ("openai_key", re.compile(r"\bsk-(?:proj-|live-)?[A-Za-z0-9_\-]{20,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("postgres_dsn_with_password", re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^:\s/'\"]+:(?!\*|<|\$\{|password@|PASSWORD@|changeme@|postgres@)[^@\s'\"]{3,}@")),
    ("supabase_secret_key", re.compile(r"\bsb_secret_[A-Za-z0-9_\-]{10,}")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
]
# Client-only rules (frontend source and built bundle)
CLIENT = [
    ("service_role_in_client", re.compile(r"service[_-]?role", re.I)),
    ("token_in_web_storage", re.compile(r"(?:local|session)Storage\.setItem\([^)]*(?:token|jwt|refresh|access|session|auth)", re.I)),
    # Actual env *access* from client code (a bare variable name inside an error-message fixture is not a leak).
    ("server_env_in_client", re.compile(
        r"(?:import\.meta\.env|process\.env)\.(?:OPENAI_API_KEY|DATABASE_URL|SESSION_SECRET|SUPABASE_JWT_SECRET"
        r"|SUPABASE_SERVICE_ROLE\w*|SUPABASE_SECRET\w*)\b")),
    ("secret_exposed_via_vite_env", re.compile(r"\bVITE_\w*(?:SECRET|SERVICE_ROLE|OPENAI|DATABASE_URL|PASSWORD)\w*")),
]
# Same-line only: [ \t]* instead of \s* so an empty `KEY=` does not swallow the next line's text.
ASSIGNED_SECRET = re.compile(
    r"^[ \t]*(?:export[ \t]+)?(OPENAI_API_KEY|SESSION_SECRET|DATABASE_URL|SUPABASE_SERVICE_ROLE_KEY|SUPABASE_SECRET_KEY"
    r"|SUPABASE_JWT_SECRET)[ \t]*[=:][ \t]*([^\s#]+)", re.M)
# Narrow, reviewed exceptions: (repo-relative path, exact matched line text). Each needs a reason and is
# additionally accepted only when the DSN host is loopback. Anything else on that path is still reported.
ALLOWLIST = {
    (".github/workflows/ci.yml",
     "TEST_DATABASE_URL: postgresql://postgres:local-ci-only@127.0.0.1:5432/tfe_test"):
        "throwaway CI service container (postgres:17-alpine) reachable only on the runner's loopback",
}
LOOPBACK_DSN = re.compile(r"@(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?/")
PLACEHOLDER = re.compile(r"^(?:.*….*|.*<[^>]+>.*|\$\{.*\}|changeme|change-me|replace[-_]?me|placeholder|xxx+|\*+|\"\"|''|your[-_].*|example.*|dummy.*|test.*|postgresql://user:password@.*|postgresql\+\w+://user:password@.*)$", re.I)


def redact(s: str) -> str:
    return s[:8] + "…(redacted)"


def iter_files(paths):
    for base in paths:
        base = Path(base)
        if base.is_file():
            yield base
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                p = Path(dirpath) / name
                if p.suffix.lower() in SKIP_SUFFIXES:
                    continue
                yield p


def is_client(rel: Path) -> bool:
    return any(part in ("frontend", "prototype", "dist", "static") for part in rel.parts)


def _relative(p: Path, bases) -> Path:
    """Repo-relative when inside the repo, else relative to the scanned base (keeps rules path-aware)."""
    rp = p.resolve()
    for base in [ROOT, *[Path(b).resolve() for b in bases]]:
        try:
            return rp.relative_to(base)
        except ValueError:
            continue
    return p


def scan(paths) -> list[tuple[str, str, str, int, str]]:
    findings = []
    for p in iter_files(paths):
        rel = _relative(p, paths)
        if any(rel.parts[: len(x.parts)] == x.parts for x in SELF_EXCLUDE):
            continue
        name = p.name
        if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
            findings.append(("HIGH", "dotenv_file_present", str(rel), 0, "real .env file in tree"))
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lines = text.splitlines()
        rules = HIGH + (CLIENT if is_client(rel) else [])
        for i, line in enumerate(lines, 1):
            allowed = (rel.as_posix(), line.strip()) in ALLOWLIST and LOOPBACK_DSN.search(line)
            for label, rx in rules:
                m = rx.search(line)
                if m and allowed and label == "postgres_dsn_with_password":
                    continue
                if m:
                    findings.append(("HIGH", label, str(rel), i, redact(m.group(0))))
        for m in ASSIGNED_SECRET.finditer(text):
            value = m.group(2).strip().strip("'\"")
            if value and not PLACEHOLDER.match(value):
                line_no = text.count("\n", 0, m.start()) + 1
                sev = "HIGH" if not name.endswith((".md",)) else "MEDIUM"
                findings.append((sev, "assigned_secret_value", str(rel), line_no, f"{m.group(1)}={redact(value)}"))
    return findings


def docker_checks() -> list[tuple[str, str, str, int, str]]:
    out = []
    dockerfiles = [p for p in iter_files([ROOT]) if p.name == "Dockerfile" or p.name.endswith(".Dockerfile")]
    if not dockerfiles:
        return out
    di = ROOT / ".dockerignore"
    if not di.exists():
        out.append(("HIGH", "dockerignore_missing", ".dockerignore", 0, "Docker context may include .env"))
    else:
        content = di.read_text()
        if not re.search(r"^\s*\**/?\.env\b", content, re.M):
            out.append(("HIGH", "dockerignore_no_env", ".dockerignore", 0, ".env not excluded from image"))
    for df in dockerfiles:
        t = df.read_text(errors="ignore")
        if re.search(r"^\s*USER\s+(?!root\b)\S+", t, re.M) is None:
            out.append(("MEDIUM", "container_runs_as_root", str(df.relative_to(ROOT)), 0, "no non-root USER (spec §13)"))
        if re.search(r"^\s*(?:ARG|ENV)\s+(?:OPENAI_API_KEY|SESSION_SECRET|DATABASE_URL)\b", t, re.M):
            out.append(("HIGH", "secret_baked_in_image", str(df.relative_to(ROOT)), 0, "secret via ARG/ENV"))
    return out


def main(argv):
    paths = [ROOT / a if not os.path.isabs(a) else Path(a) for a in argv[1:]] or [ROOT]
    findings = scan(paths) + (docker_checks() if len(argv) == 1 else [])
    for sev, label, path, line, detail in findings:
        print(f"{sev:6} {label:28} {path}:{line}  {detail}")
    high = sum(1 for f in findings if f[0] == "HIGH")
    print(f"scan_secrets: {len(findings)} finding(s), {high} HIGH, scanned {', '.join(str(p) for p in paths)}")
    return 1 if high else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
