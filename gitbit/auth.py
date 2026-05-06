"""Authentication helpers for gitbit."""
from __future__ import annotations

import os
from urllib.parse import urlparse, urlunparse

from .config import AuthConfig
from .exceptions import AuthError


def build_auth_env(auth: AuthConfig | None, base_env: dict) -> dict:
    """Return a copy of base_env with SSH credentials set if applicable.

    For SSH auth, sets GIT_SSH_COMMAND to use the specified private key with
    StrictHostKeyChecking=accept-new and BatchMode=yes (no interactive prompts).
    For HTTPS auth, token injection happens in inject_https_token — no env changes.
    """
    env = base_env.copy()
    if auth is None:
        return env
    if auth.type == "ssh":
        if auth.private_key:
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {auth.private_key} -o StrictHostKeyChecking=accept-new"
                " -o BatchMode=yes"
            )
    return env


def inject_https_token(url: str, auth: AuthConfig | None) -> str:
    """Return url with token injected for HTTPS auth.

    Returns url unchanged if auth is None or type is ssh.
    Raises AuthError if token_env is not configured or the env var is unset.
    """
    if auth is None or auth.type != "https":
        return url
    if auth.token_env is None:
        raise AuthError("https auth requires token_env to be set")
    token = os.environ.get(auth.token_env)
    if not token:
        raise AuthError(f"Environment variable '{auth.token_env}' is not set or empty")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return url
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    netloc = f"oauth2:{token}@{host}"
    return urlunparse(parsed._replace(netloc=netloc))


def safe_url(url: str) -> str:
    """Return url with credentials stripped, safe for logging.

    Removes any username/password from the netloc so tokens never appear in logs.
    """
    parsed = urlparse(url)
    if parsed.password or parsed.username:
        safe = parsed._replace(netloc=parsed.hostname or "")
        return urlunparse(safe)
    return url
