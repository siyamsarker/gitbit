"""Tests for gitbit.auth."""
from __future__ import annotations

import os

import pytest

from gitbit.auth import build_auth_env, inject_https_token, safe_url
from gitbit.config import AuthConfig
from gitbit.exceptions import AuthError


class TestBuildAuthEnv:
    def test_no_auth_returns_copy_of_base(self) -> None:
        base = {"PATH": "/usr/bin", "HOME": "/home/user"}
        result = build_auth_env(None, base)
        assert result == base
        assert result is not base  # must be a copy

    def test_ssh_with_private_key_sets_git_ssh_command(self) -> None:
        auth = AuthConfig(type="ssh", private_key="/home/user/.ssh/id_ed25519")
        base = {"PATH": "/usr/bin"}
        result = build_auth_env(auth, base)
        assert "GIT_SSH_COMMAND" in result
        assert "/home/user/.ssh/id_ed25519" in result["GIT_SSH_COMMAND"]
        assert "StrictHostKeyChecking=accept-new" in result["GIT_SSH_COMMAND"]
        assert "BatchMode=yes" in result["GIT_SSH_COMMAND"]

    def test_ssh_without_private_key_no_git_ssh_command(self) -> None:
        auth = AuthConfig(type="ssh", private_key=None)
        base = {"PATH": "/usr/bin"}
        result = build_auth_env(auth, base)
        assert "GIT_SSH_COMMAND" not in result

    def test_https_auth_does_not_modify_env(self) -> None:
        auth = AuthConfig(type="https", token_env="MY_TOKEN")
        base = {"PATH": "/usr/bin"}
        result = build_auth_env(auth, base)
        # HTTPS token injection is handled elsewhere; env should be unchanged
        assert "GIT_SSH_COMMAND" not in result
        assert result["PATH"] == "/usr/bin"

    def test_does_not_mutate_base_env(self) -> None:
        auth = AuthConfig(type="ssh", private_key="/tmp/key")
        base = {"PATH": "/usr/bin"}
        build_auth_env(auth, base)
        assert "GIT_SSH_COMMAND" not in base


class TestInjectHttpsToken:
    def test_injects_token_into_https_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_TOKEN", "s3cr3t")
        auth = AuthConfig(type="https", token_env="MY_TOKEN")
        url = "https://gitlab.com/org/repo.git"
        result = inject_https_token(url, auth)
        assert "s3cr3t" in result
        assert "oauth2:" in result
        assert result.startswith("https://oauth2:s3cr3t@gitlab.com")

    def test_no_auth_returns_url_unchanged(self) -> None:
        url = "https://github.com/org/repo.git"
        result = inject_https_token(url, None)
        assert result == url

    def test_ssh_auth_returns_url_unchanged(self) -> None:
        auth = AuthConfig(type="ssh", private_key="/tmp/key")
        url = "git@github.com:org/repo.git"
        result = inject_https_token(url, auth)
        assert result == url

    def test_missing_token_env_var_raises_auth_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MISSING_TOKEN", raising=False)
        auth = AuthConfig(type="https", token_env="MISSING_TOKEN")
        with pytest.raises(AuthError, match="MISSING_TOKEN"):
            inject_https_token("https://example.com/repo.git", auth)

    def test_empty_token_env_var_raises_auth_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EMPTY_TOKEN", "")
        auth = AuthConfig(type="https", token_env="EMPTY_TOKEN")
        with pytest.raises(AuthError, match="EMPTY_TOKEN"):
            inject_https_token("https://example.com/repo.git", auth)

    def test_none_token_env_raises_auth_error(self) -> None:
        auth = AuthConfig(type="https", token_env=None)
        with pytest.raises(AuthError, match="token_env"):
            inject_https_token("https://example.com/repo.git", auth)

    def test_non_http_url_returned_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_TOKEN", "token123")
        auth = AuthConfig(type="https", token_env="MY_TOKEN")
        url = "git@github.com:org/repo.git"
        result = inject_https_token(url, auth)
        assert result == url

    def test_url_with_port_preserves_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_TOKEN", "tok")
        auth = AuthConfig(type="https", token_env="MY_TOKEN")
        url = "https://git.example.com:8443/org/repo.git"
        result = inject_https_token(url, auth)
        assert "8443" in result
        assert "oauth2:tok@git.example.com:8443" in result


class TestSafeUrl:
    def test_url_without_credentials_unchanged(self) -> None:
        url = "https://github.com/org/repo.git"
        assert safe_url(url) == url

    def test_url_with_password_redacted(self) -> None:
        url = "https://oauth2:s3cr3t@github.com/org/repo.git"
        result = safe_url(url)
        assert "s3cr3t" not in result
        assert "github.com" in result

    def test_url_with_username_redacted(self) -> None:
        url = "https://myuser@github.com/org/repo.git"
        result = safe_url(url)
        assert "myuser" not in result
        assert "github.com" in result

    def test_ssh_url_no_credentials_unchanged(self) -> None:
        url = "git@github.com:org/repo.git"
        assert safe_url(url) == url
