"""Application-repository hygiene after the split from the DevOps repository.

Container image, compose files, the production config template and the container smoke test live in the
separate `time-for-everything_deploy` repository (its own contract tests). What stays here: secret material
is git-ignored, the temporarily nested deploy root is excluded, and source CI builds/deploys no image.
Application config behaviour itself is covered by test_config_secrets.py.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
NESTED_DEPLOY_ROOT = "time-for-everything_deploy"


def _gitignore_lines() -> set[str]:
    return {line.strip() for line in (REPO / ".gitignore").read_text().splitlines()}


def test_gitignore_excludes_secret_material():
    needles = ["*.env", "*.env.*", "!*.env.example", "secrets/", "*.p12", "*.pfx", "*.pem", "*.key", "*.bak", "*.dump",
               ".claude/settings.local.json"]
    missing = [n for n in needles if n not in _gitignore_lines()]
    assert not missing, missing


def test_nested_deploy_repository_is_excluded():
    assert f"/{NESTED_DEPLOY_ROOT}/" in _gitignore_lines()


@pytest.mark.parametrize("name", ["compose.yaml", "compose.production.yaml", ".dockerignore", "infra"])
def test_no_container_or_deploy_artifacts_in_app_root(name):
    assert not (REPO / name).exists(), f"{name} belongs to the {NESTED_DEPLOY_ROOT} repository"


def test_no_dockerfile_in_application_tree():
    skip = {NESTED_DEPLOY_ROOT, "node_modules", ".venv", ".git", "dist", "__pycache__"}
    found = []
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d not in skip]
        found += [os.path.join(dirpath, f) for f in filenames if "Dockerfile" in f or f == ".dockerignore"]
    assert not found, found


def test_app_workflows_dir_holds_only_source_ci():
    # A deploy/release workflow (or a stale copy of one) must never live in the application repository.
    entries = sorted(p.name for p in (REPO / ".github" / "workflows").iterdir())
    assert entries == ["ci.yml"], entries


def test_source_ci_actions_are_pinned_to_commit_shas():
    text = (REPO / ".github" / "workflows" / "ci.yml").read_text()
    uses = [line.split("uses:", 1)[1].split("#")[0].strip() for line in text.splitlines() if "uses:" in line]
    assert uses
    bad = [u for u in uses if not re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u)]
    assert not bad, bad


def test_source_ci_builds_and_deploys_no_image():
    path = REPO / ".github" / "workflows" / "ci.yml"
    doc = yaml.safe_load(path.read_text())
    assert set(doc["jobs"]) == {"backend", "postgres", "frontend"}
    text = path.read_text()
    for forbidden in ("docker build", "buildx", "docker push", "docker login", "docker compose", "${{ secrets."):
        assert forbidden not in text, forbidden
