"""Exercise real release tooling in disposable repositories, without publishing."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("custom_components/ac_infinity/manifest.json")


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.mark.parametrize(
    ("message", "version"),
    [
        ("fix: handle a disconnected load", "1.0.4"),
        ("feat: support another load", "1.1.0"),
        ("feat!: require a newer Home Assistant", "2.0.0"),
        ("fix: update runtime\n\nBREAKING CHANGE: Require a newer runtime.", "2.0.0"),
        ("docs: clarify installation", "1.0.3"),
    ],
)
def test_release_updates_tagged_manifest(tmp_path: Path, message: str, version: str):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "Release test")
    git(tmp_path, "config", "user.email", "release-test@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "config", "tag.gpgsign", "false")
    git(
        tmp_path,
        "remote",
        "add",
        "origin",
        "https://github.com/example/integration.git",
    )
    shutil.copyfile(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    manifest = json.loads((ROOT / MANIFEST).read_text())
    manifest["version"] = "1.0.3"
    (tmp_path / MANIFEST).parent.mkdir(parents=True)
    (tmp_path / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "chore: initial release")
    git(tmp_path, "tag", "v1.0.3")
    git(tmp_path, "commit", "--allow-empty", "-m", message)
    env = os.environ.copy()
    # Never use CI credentials or write to the caller's GitHub step outputs.
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_OUTPUT", "GITHUB_ACTIONS"):
        env.pop(key, None)
    command = [
        sys.executable,
        "-m",
        "semantic_release",
        "version",
        "--no-push",
        "--no-vcs-release",
    ]
    result = subprocess.run(
        command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stdout + result.stderr
    tagged = json.loads(git(tmp_path, "show", f"v{version}:{MANIFEST.as_posix()}"))
    assert tagged == {**manifest, "version": version}
    assert json.loads((tmp_path / MANIFEST).read_text()) == tagged
    # A retry must not manufacture another release or change the tagged files.
    head = git(tmp_path, "rev-parse", "HEAD")
    subprocess.run(command, cwd=tmp_path, env=env, check=True, capture_output=True)
    assert git(tmp_path, "rev-parse", "HEAD") == head
    assert not git(tmp_path, "status", "--porcelain")
