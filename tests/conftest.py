"""Shared pytest fixtures for git-mirror tests."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_mirrors_dir(tmp_path: Path) -> str:
    """Return a temporary directory path to use as mirrors_dir."""
    d = tmp_path / "mirrors"
    d.mkdir()
    return str(d)


@pytest.fixture()
def sample_config_dict(tmp_path: Path) -> dict:
    """Return a minimal valid config dict."""
    return {
        "global": {
            "parallel": 2,
            "timeout": 60,
            "verbose": False,
            "mirrors_dir": str(tmp_path / "mirrors"),
        },
        "repos": [
            {
                "name": "RepoA",
                "source": "git@github.com:org/RepoA.git",
                "dest": "git@backup.example.com:mirrors/RepoA.git",
                "auth": {"type": "ssh", "private_key": "~/.ssh/id_rsa"},
                "lfs": False,
                "submodules": False,
            },
            {
                "name": "RepoB",
                "source": "https://gitlab.com/team/RepoB.git",
                "dest": "https://git.example.com/team/RepoB.git",
                "auth": {"type": "https", "token_env": "GITLAB_TOKEN"},
                "lfs": False,
                "submodules": False,
            },
        ],
    }


@pytest.fixture()
def config_file(tmp_path: Path, sample_config_dict: dict) -> str:
    """Write sample_config_dict to a temp JSON file and return its path."""
    p = tmp_path / "repos.json"
    p.write_text(json.dumps(sample_config_dict))
    return str(p)


@pytest.fixture()
def ssh_repo_config():
    """Return a RepoConfig-compatible dict for SSH auth."""
    from git_mirror.config import AuthConfig, RepoConfig

    return RepoConfig(
        name="TestSSH",
        source="git@github.com:org/test.git",
        dest="git@backup.example.com:mirrors/test.git",
        auth=AuthConfig(type="ssh", private_key="/tmp/id_rsa"),
        lfs=False,
    )


@pytest.fixture()
def https_repo_config():
    """Return a RepoConfig-compatible object for HTTPS auth."""
    from git_mirror.config import AuthConfig, RepoConfig

    return RepoConfig(
        name="TestHTTPS",
        source="https://gitlab.com/team/test.git",
        dest="https://git.example.com/team/test.git",
        auth=AuthConfig(type="https", token_env="TEST_TOKEN"),
        lfs=False,
    )
