"""Tests for git_mirror.config."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from git_mirror.config import Config, GlobalConfig, RepoConfig, load_config
from git_mirror.exceptions import ConfigError


class TestLoadConfig:
    def test_load_valid_config(self, config_file: str) -> None:
        cfg = load_config(config_file)
        assert isinstance(cfg, Config)
        assert len(cfg.repos) == 2
        assert cfg.repos[0].name == "RepoA"
        assert cfg.repos[1].name == "RepoB"

    def test_global_defaults_applied(self, config_file: str) -> None:
        cfg = load_config(config_file)
        assert cfg.global_config.parallel == 2
        assert cfg.global_config.timeout == 60

    def test_missing_file_raises_config_error(self, tmp_path: Path) -> None:
        missing = str(tmp_path / "nonexistent.json")
        with pytest.raises(ConfigError, match="Config file not found"):
            load_config(missing)

    def test_invalid_json_raises_config_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{ not valid json }")
        with pytest.raises(ConfigError, match="Invalid JSON in config"):
            load_config(str(bad))

    def test_schema_violation_raises_config_error(self, tmp_path: Path) -> None:
        # parallel must be >= 1 and <= 32
        data = {
            "global": {"parallel": 999},
            "repos": [],
        }
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps(data))
        with pytest.raises(ConfigError, match="Config validation failed"):
            load_config(str(p))

    def test_repo_missing_required_field_raises(self, tmp_path: Path) -> None:
        data = {
            "repos": [
                {"name": "Incomplete"}  # missing source and dest
            ]
        }
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps(data))
        with pytest.raises(ConfigError, match="Config validation failed"):
            load_config(str(p))

    def test_empty_repos_list(self, tmp_path: Path) -> None:
        data = {"repos": []}
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps(data))
        cfg = load_config(str(p))
        assert cfg.repos == []

    def test_global_config_defaults_without_global_key(self, tmp_path: Path) -> None:
        data = {
            "repos": [
                {"name": "R", "source": "git@x.com:org/r.git", "dest": "git@y.com:org/r.git"}
            ]
        }
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps(data))
        cfg = load_config(str(p))
        # defaults should be applied
        assert cfg.global_config.parallel == 4
        assert cfg.global_config.timeout == 300


class TestAuthConfigExpansion:
    def test_private_key_tilde_expanded(self) -> None:
        from git_mirror.config import AuthConfig

        auth = AuthConfig(type="ssh", private_key="~/some/key")
        assert not auth.private_key.startswith("~")
        assert auth.private_key == os.path.expanduser("~/some/key")

    def test_private_key_env_var_expanded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KEYDIR", "/opt/keys")
        from git_mirror.config import AuthConfig

        auth = AuthConfig(type="ssh", private_key="$KEYDIR/id_rsa")
        assert auth.private_key == "/opt/keys/id_rsa"

    def test_private_key_none_stays_none(self) -> None:
        from git_mirror.config import AuthConfig

        auth = AuthConfig(type="ssh", private_key=None)
        assert auth.private_key is None


class TestGlobalConfigExpansion:
    def test_mirrors_dir_tilde_expanded(self) -> None:
        gc = GlobalConfig(mirrors_dir="~/.git-mirror/mirrors")
        assert not gc.mirrors_dir.startswith("~")
        assert gc.mirrors_dir == os.path.expanduser("~/.git-mirror/mirrors")

    def test_mirrors_dir_env_var_expanded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIRRORBASE", "/data/mirrors")
        gc = GlobalConfig(mirrors_dir="$MIRRORBASE/repos")
        assert gc.mirrors_dir == "/data/mirrors/repos"
