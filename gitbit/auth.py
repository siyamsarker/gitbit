"""
Authentication helpers for gitbit.

This module handles credential setup for both supported auth methods so that
every other module can stay credential-agnostic — they just call build_auth_env()
and inject_https_token() without knowing the details.

SSH authentication
------------------
gitbit sets the GIT_SSH_COMMAND environment variable to point git at a specific
private key file. The options used are:

  -o StrictHostKeyChecking=accept-new
      Automatically accepts a host key the first time it is seen, but rejects
      changed keys. Prevents interactive "yes/no" prompts in automated pipelines
      without disabling host verification entirely.

  -o BatchMode=yes
      Disables all interactive prompts. If the key fails, git exits immediately
      instead of asking for a passphrase. Required for non-interactive use.

If no private key is configured, GIT_SSH_COMMAND is left unset and git falls
back to the SSH agent and default key files (~/.ssh/id_rsa, etc.).

HTTPS authentication
--------------------
Tokens are injected directly into the URL in OAuth2 format:
    https://oauth2:<token>@host/org/repo.git

This is the format accepted by GitHub, GitLab, Gitea, and most other platforms
for personal access token (PAT) authentication. The token is read from an
environment variable at call time and never stored in the config file or logs.

Credential safety
-----------------
  - shlex.quote() prevents shell injection via unusual key path characters.
    GIT_SSH_COMMAND is a shell string (not a list), so quoting is mandatory.
  - safe_url() strips credentials before any URL is passed to a logger.
  - No credential value is ever written to disk by this module.
"""
from __future__ import annotations

import os
import shlex
from urllib.parse import urlparse, urlunparse

from .config import AuthConfig
from .exceptions import AuthError


def build_auth_env(auth: AuthConfig | None, base_env: dict[str, str]) -> dict[str, str]:
    """Build the subprocess environment dictionary for git credential setup.

    Returns a copy of base_env with SSH credentials configured when applicable.
    HTTPS auth does not modify the environment — token injection into the URL
    is handled separately by inject_https_token().

    Args:
        auth:     Authentication configuration from the repo config, or None.
                  When None, the function returns base_env unchanged and git
                  uses the ambient SSH agent and default key files.
        base_env: The base environment to copy and augment. Should be
                  os.environ.copy() from the calling thread so each thread
                  gets its own copy and they do not share state.

    Returns:
        A new dict based on base_env. For SSH auth with a private_key configured,
        GIT_SSH_COMMAND is added to force git to use that specific key file with
        non-interactive options. All other cases return the dict unchanged.
    """
    env = base_env.copy()
    if auth is None:
        return env
    if auth.type == "ssh":
        if auth.private_key:
            # shlex.quote() is required here because GIT_SSH_COMMAND is
            # interpreted as a shell string by the SSH binary. A key path
            # containing spaces or special characters would otherwise break
            # the command. We never use shell=True in subprocess calls, but
            # this string is still parsed by the shell that git invokes for SSH.
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {shlex.quote(auth.private_key)} -o StrictHostKeyChecking=accept-new"
                " -o BatchMode=yes"
            )
    return env


def inject_https_token(url: str, auth: AuthConfig | None) -> str:
    """Inject an OAuth2 bearer token into an HTTPS repository URL.

    Transforms the URL from the unauthenticated form:
        https://github.com/org/repo.git
    into the token-authenticated form:
        https://oauth2:<token>@github.com/org/repo.git

    The token is read from the environment variable named by auth.token_env
    at call time. It is embedded in the URL netloc so git passes it to the
    remote via HTTP Basic Auth (username=oauth2, password=<token>), which is
    the standard PAT authentication mechanism for most Git hosting platforms.

    The returned URL must be passed to safe_url() before logging to prevent
    the token from appearing in log output.

    Args:
        url:  The original repository URL. Returned unchanged if the URL is
              not HTTP/HTTPS, or if auth is None or auth.type is 'ssh'.
        auth: Authentication configuration. Must have type='https' and a
              non-None token_env value that names a set environment variable.

    Returns:
        URL string with the OAuth2 token embedded in the netloc for HTTPS repos.
        Returns url unchanged for SSH repos, non-HTTP URLs, or when auth is None.

    Raises:
        AuthError: If auth.token_env is None (token source not configured).
        AuthError: If the environment variable named by token_env is not set
                   or resolves to an empty string.
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
    # urlparse separates hostname and port into distinct attributes, so we must
    # reconstruct the host string manually before building the new netloc.
    # Omitting the port here would silently strip non-standard ports (e.g. :8080).
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    netloc = f"oauth2:{token}@{host}"
    return urlunparse(parsed._replace(netloc=netloc))


def safe_url(url: str) -> str:
    """Strip credentials from a URL so it is safe to include in log messages.

    After inject_https_token() embeds a token in a URL, that URL must never
    be passed directly to any logger. This function removes the username and
    password from the netloc while preserving the host, port, path, and query.

    Example:
        Input:  https://oauth2:ghp_secret@github.com:443/org/repo.git
        Output: https://github.com:443/org/repo.git

    Args:
        url: Any URL string, with or without embedded credentials.

    Returns:
        The URL with username and password removed from the netloc.
        Returns url unchanged if no credentials are present, avoiding
        unnecessary parsing overhead on plain URLs.
    """
    parsed = urlparse(url)
    if parsed.password or parsed.username:
        # Rebuild the netloc as bare host[:port] with no credentials.
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunparse(parsed._replace(netloc=host))
    return url
