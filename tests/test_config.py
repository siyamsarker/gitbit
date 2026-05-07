"""Tests for gitbit.config."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from gitbit.config import Config, GlobalConfig, RepoConfig, ValidationIssue, load_config, validate_config
from gitbit.exceptions import ConfigError


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
        from gitbit.config import AuthConfig

        auth = AuthConfig(type="ssh", private_key="~/some/key")
        assert not auth.private_key.startswith("~")
        assert auth.private_key == os.path.expanduser("~/some/key")

    def test_private_key_env_var_expanded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KEYDIR", "/opt/keys")
        from gitbit.config import AuthConfig

        auth = AuthConfig(type="ssh", private_key="$KEYDIR/id_rsa")
        assert auth.private_key == "/opt/keys/id_rsa"

    def test_private_key_none_stays_none(self) -> None:
        from gitbit.config import AuthConfig

        auth = AuthConfig(type="ssh", private_key=None)
        assert auth.private_key is None


class TestGlobalConfigExpansion:
    def test_mirrors_dir_tilde_expanded(self) -> None:
        gc = GlobalConfig(mirrors_dir="~/.gitbit/mirrors")
        assert not gc.mirrors_dir.startswith("~")
        assert gc.mirrors_dir == os.path.expanduser("~/.gitbit/mirrors")

    def test_mirrors_dir_env_var_expanded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIRRORBASE", "/data/mirrors")
        gc = GlobalConfig(mirrors_dir="$MIRRORBASE/repos")
        assert gc.mirrors_dir == "/data/mirrors/repos"


class TestValidateConfig:
    def _cfg(self, tmp_path: "Path", repos: list | None = None) -> "Config":
        """Build a minimal valid Config with mirrors_dir pointing at an existing tmp dir."""
        from gitbit.config import AuthConfig, Config, GlobalConfig, RepoConfig

        mirrors = tmp_path / "mirrors"
        mirrors.mkdir()
        return Config(
            **{
                "global": GlobalConfig(mirrors_dir=str(mirrors)),
                "repos": repos or [],
            }
        )

    def test_clean_config_returns_no_issues(self, tmp_path: "Path") -> None:
        cfg = self._cfg(tmp_path)
        assert validate_config(cfg) == []

    def test_missing_mirrors_dir_is_warning(self, tmp_path: "Path") -> None:
        from gitbit.config import Config, GlobalConfig

        cfg = Config(
            **{"global": GlobalConfig(mirrors_dir=str(tmp_path / "nonexistent")), "repos": []}
        )
        issues = validate_config(cfg)
        assert any(i.severity == "warning" and i.field == "mirrors_dir" for i in issues)

    def test_duplicate_repo_name_is_error(self, tmp_path: "Path") -> None:
        from gitbit.config import RepoConfig

        repo = RepoConfig(name="Dup", source="git@x.com:a.git", dest="git@y.com:a.git")
        cfg = self._cfg(tmp_path, repos=[repo, repo])
        issues = validate_config(cfg)
        assert any(i.severity == "error" and "Dup" in i.message for i in issues)

    def test_missing_https_token_env_is_error(
        self, tmp_path: "Path", monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from gitbit.config import AuthConfig, RepoConfig

        monkeypatch.delenv("MISSING_TOK", raising=False)
        repo = RepoConfig(
            name="R",
            source="https://x.com/r.git",
            dest="https://y.com/r.git",
            auth=AuthConfig(type="https", token_env="MISSING_TOK"),
        )
        cfg = self._cfg(tmp_path, repos=[repo])
        issues = validate_config(cfg)
        assert any(
            i.severity == "error" and "MISSING_TOK" in i.message and i.repo == "R"
            for i in issues
        )

    def test_set_https_token_env_passes(
        self, tmp_path: "Path", monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from gitbit.config import AuthConfig, RepoConfig

        monkeypatch.setenv("MY_TOK", "secret")
        repo = RepoConfig(
            name="R",
            source="https://x.com/r.git",
            dest="https://y.com/r.git",
            auth=AuthConfig(type="https", token_env="MY_TOK"),
        )
        cfg = self._cfg(tmp_path, repos=[repo])
        issues = [i for i in validate_config(cfg) if i.severity == "error"]
        assert issues == []

    def test_missing_ssh_key_file_is_error(self, tmp_path: "Path") -> None:
        from gitbit.config import AuthConfig, RepoConfig

        repo = RepoConfig(
            name="R",
            source="git@x.com:r.git",
            dest="git@y.com:r.git",
            auth=AuthConfig(type="ssh", private_key="/nonexistent/key"),
        )
        cfg = self._cfg(tmp_path, repos=[repo])
        issues = validate_config(cfg)
        assert any(
            i.severity == "error" and "private_key" in i.field and i.repo == "R"
            for i in issues
        )

    def test_existing_ssh_key_file_passes(self, tmp_path: "Path") -> None:
        from gitbit.config import AuthConfig, RepoConfig

        key = tmp_path / "id_rsa"
        key.write_text("fake key")
        repo = RepoConfig(
            name="R",
            source="git@x.com:r.git",
            dest="git@y.com:r.git",
            auth=AuthConfig(type="ssh", private_key=str(key)),
        )
        cfg = self._cfg(tmp_path, repos=[repo])
        issues = [i for i in validate_config(cfg) if i.severity == "error"]
        assert issues == []
