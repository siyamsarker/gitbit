"""
Configuration models and JSON loader for gitbit.

This module owns the entire configuration schema. It uses Pydantic v2 models
for two reasons: automatic type coercion (e.g. strings to ints) and structured
error messages that tell the user exactly which field is wrong and why.

Config file structure (repos.json):
------------------------------------
    {
      "global": {           <- optional; all fields have defaults
        "parallel":    4,
        "timeout":     300,
        "verbose":     false,
        "mirrors_dir": "~/.gitbit/mirrors"
      },
      "repos": [            <- required; may be empty []
        {
          "name":   "ProjectA",
          "source": "git@github.com:org/ProjectA.git",
          "dest":   "git@backup.example.com:mirrors/ProjectA.git",
          "auth":   { "type": "ssh", "private_key": "~/.ssh/id_deploy" },
          "lfs":    true
        }
      ]
    }

Loading vs. validation
-----------------------
load_config()     — Parses JSON and validates schema structure. Fast, offline.
                    Raises ConfigError on any structural problem.

validate_config() — Performs semantic checks that schema validation cannot do:
                    env var existence, SSH key file presence, duplicate names.
                    Returns a list of ValidationIssue rather than raising, so
                    all findings can be displayed at once (used by `gitbit validate`).

Path expansion
--------------
Both AuthConfig.private_key and GlobalConfig.mirrors_dir apply os.expanduser()
and os.expandvars() via Pydantic field validators, so paths like
'~/keys/id_rsa' and '$HOME/mirrors' work transparently.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from .exceptions import ConfigError


class AuthConfig(BaseModel):
    """Authentication configuration for a single repository.

    Specifies how gitbit should authenticate when talking to the source
    or destination Git remote. Two methods are supported:

    SSH key authentication (type='ssh'):
        gitbit sets GIT_SSH_COMMAND to use a specific private key file.
        If private_key is omitted, git uses the ambient SSH agent and
        default key files (~/.ssh/id_rsa, etc.) from the calling environment.

    HTTPS token authentication (type='https'):
        gitbit reads a bearer token from the named environment variable at
        runtime and injects it into the URL as oauth2:<token>@host. The token
        itself is never stored in this config; only the variable name is.

    Attributes:
        type:        Authentication method. Must be 'ssh' or 'https'.
        private_key: Path to the SSH private key file. ~ and $ENVVAR are
                     expanded at parse time. Only relevant when type='ssh'.
        token_env:   Name of the environment variable that holds the HTTPS
                     access token (e.g. 'GITHUB_TOKEN'). Only relevant when
                     type='https'.
    """

    type: Literal["ssh", "https"]
    private_key: Optional[str] = None  # path to SSH private key; ~ and $VAR expanded
    token_env: Optional[str] = None    # name of env var holding the HTTPS bearer token

    @field_validator("private_key")
    @classmethod
    def expand_key_path(cls, v: Optional[str]) -> Optional[str]:
        """Expand ~ and $ENVVAR references in the SSH key path at parse time.

        Expanding at parse time (rather than at use time) means the stored path
        is always a fully resolved absolute path, avoiding repeated expansion and
        making the value safe to compare against os.path.exists() directly.
        """
        if v:
            return os.path.expandvars(os.path.expanduser(v))
        return v


class RepoConfig(BaseModel):
    """Configuration for a single repository mirror operation.

    Each entry in the 'repos' list of the config file maps to one RepoConfig.
    The name is used both as a human-readable label and as the local mirror
    directory name: <mirrors_dir>/<name>.git

    Attributes:
        name:   Unique identifier for this repository. Used as:
                  - A label in log output and status tables.
                  - The local mirror directory name (<name>.git).
                Must be unique across all repos in the config; duplicates
                are caught by validate_config().
        source: URL of the source repository to clone/fetch from.
                Supports SSH format (git@host:org/repo.git) and
                HTTPS format (https://host/org/repo.git).
        dest:   URL of the destination repository to push to.
                Same format options as source.
        auth:   Authentication configuration. When None, gitbit inherits
                credentials from the calling environment (SSH agent, netrc,
                etc.). A single auth block is used for both source and dest.
        lfs:    When True, fetch and push Git LFS objects in addition to
                standard refs. Requires git-lfs to be installed on the system.
                Defaults to False.
    """

    name: str
    source: str
    dest: str
    auth: Optional[AuthConfig] = None
    lfs: bool = False


class GlobalConfig(BaseModel):
    """Global settings that apply to all repositories in a config file.

    All fields are optional — omitting the entire 'global' section from the
    JSON file is valid and applies the defaults listed below.

    Attributes:
        parallel:    Maximum number of repositories processed concurrently.
                     Constrained to [1, 32]. Higher values speed up large
                     batches but increase memory and network load. Default: 4.
        timeout:     Maximum seconds allowed for any single git operation
                     (clone, fetch, or push). Operations that exceed this are
                     killed and retried. Constrained to >= 10. Default: 300.
        verbose:     When True, enables DEBUG-level logging, which includes
                     every git command, every retry attempt, and timing info.
                     Default: False.
        mirrors_dir: Root directory where all bare mirror clones are stored.
                     Each repo creates a subdirectory: <mirrors_dir>/<name>.git
                     ~ and $ENVVAR are expanded at parse time. Default:
                     ~/.gitbit/mirrors
    """

    parallel: int = Field(default=4, ge=1, le=32)
    timeout: int = Field(default=300, ge=10)
    verbose: bool = False
    mirrors_dir: str = Field(default="~/.gitbit/mirrors")

    @field_validator("mirrors_dir")
    @classmethod
    def expand_dir(cls, v: str) -> str:
        """Expand ~ and $ENVVAR references in the mirrors directory path at parse time."""
        return os.path.expandvars(os.path.expanduser(v))


class Config(BaseModel):
    """Root configuration model representing a complete gitbit config file.

    This is the top-level object returned by load_config(). It maps directly
    to the JSON structure: a 'global' section and a 'repos' list.

    The 'global' JSON key is a Python reserved keyword, so Pydantic's alias
    mechanism is used: the JSON field 'global' maps to the Python attribute
    'global_config'. Both names work when constructing the model programmatically
    (enabled by populate_by_name=True).

    Attributes:
        global_config: Global processing settings. Populated from the 'global'
                       JSON key. When the 'global' key is absent, all defaults
                       from GlobalConfig are applied automatically.
        repos:         Ordered list of repository mirror definitions. An empty
                       list is valid; all batch commands will succeed with no
                       repos processed.
    """

    global_config: GlobalConfig = Field(default_factory=GlobalConfig, alias="global")
    repos: list[RepoConfig] = []

    # populate_by_name=True allows constructing Config(..., global_config=...) in
    # Python code while still accepting the 'global' alias from JSON input.
    model_config = {"populate_by_name": True}


def load_config(path: str) -> Config:
    """Load and validate a gitbit configuration file from disk.

    Reads the JSON file at the given path, parses it, and validates it against
    the Config Pydantic schema. All field validators (path expansion, range
    constraints) run automatically during validation.

    Args:
        path: Filesystem path to the JSON configuration file (e.g. 'repos.json').

    Returns:
        A fully validated Config instance with all defaults applied. The returned
        object is safe to pass directly to sync functions.

    Raises:
        ConfigError: If the file does not exist at path.
        ConfigError: If the file content is not valid JSON.
        ConfigError: If the parsed JSON fails Pydantic schema validation —
                     for example, a missing required field, a value outside an
                     allowed range, or a wrong type. The error message includes
                     the Pydantic validation report for easy debugging.
    """
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}")
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in config: {e}")
    try:
        return Config.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"Config validation failed:\n{e}")


@dataclass
class ValidationIssue:
    """A single finding from validate_config().

    Issues are collected into a list and returned together rather than raising
    an exception, so the 'gitbit validate' command can display every problem
    at once instead of stopping at the first error.

    Attributes:
        field:    Dotted path to the config field that triggered the issue.
                  Examples: 'auth.token_env', 'auth.private_key', 'name',
                  'mirrors_dir'.
        message:  Human-readable description of the problem or warning.
        severity: 'error'   — will cause sync operations to fail; must be fixed.
                  'warning' — may be intentional or self-healing; does not
                              affect the validate command's exit code.
        repo:     Name of the repository this issue belongs to, or None for
                  global-level issues (e.g. mirrors_dir, duplicate repo names).
    """

    field: str
    message: str
    severity: str       # "error" | "warning"
    repo: Optional[str] = None  # None means this is a global (non-repo) issue


def validate_config(cfg: Config) -> list[ValidationIssue]:
    """Perform semantic validation of a loaded Config without network access.

    Checks things that Pydantic schema validation cannot catch at parse time —
    specifically, runtime environment state (env vars, file paths on disk) and
    logical constraints that span multiple repos (duplicate names).

    This function is safe to call in offline/air-gapped environments. It only
    reads the local filesystem and environment variables; no network calls are made.

    Checks performed (in order):
      1. Duplicate repo names (error): Each repo name is used as a directory
         name inside mirrors_dir. Duplicates would cause one repo's mirror to
         silently overwrite another's on the first sync.
      2. mirrors_dir existence (warning): The directory is created automatically
         by import_repo() on first use, so missing is expected on a fresh setup.
         It is a warning, not an error, because the sync will still succeed.
      3. HTTPS token env var set (error): If a repo uses HTTPS auth, the
         environment variable named by token_env must be set and non-empty right
         now. A missing token causes an immediate AuthError at sync time.
      4. SSH key file exists (error): If a repo specifies a private_key path,
         that file must exist on disk. A missing key file causes an immediate
         AuthError at sync time.

    Args:
        cfg: A fully loaded and schema-validated Config instance, as returned
             by load_config().

    Returns:
        A list of ValidationIssue objects, possibly empty. An empty list means
        the config passed all checks. Errors and warnings are mixed in the same
        list; callers filter by issue.severity as needed.
    """
    issues: list[ValidationIssue] = []

    # --- Check 1: Duplicate repository names ---
    # Names double as directory names; duplicates would cause one repo to
    # silently overwrite another's mirror on the first sync run.
    seen: set[str] = set()
    for repo in cfg.repos:
        if repo.name in seen:
            issues.append(ValidationIssue(
                field="name",
                message=f"Duplicate repository name '{repo.name}'",
                severity="error",
                repo=repo.name,
            ))
        seen.add(repo.name)

    # --- Check 2: mirrors_dir existence ---
    # A missing mirrors_dir is expected on a first-time setup — import_repo()
    # calls Path.mkdir(parents=True, exist_ok=True) before cloning. Flag as
    # warning so the user is aware, but don't block them from running.
    if not Path(cfg.global_config.mirrors_dir).exists():
        issues.append(ValidationIssue(
            field="mirrors_dir",
            message=(
                f"'{cfg.global_config.mirrors_dir}' does not exist"
                " — will be created automatically on first import"
            ),
            severity="warning",
        ))

    # --- Checks 3 & 4: Per-repo authentication pre-flight ---
    for repo in cfg.repos:
        if repo.auth is None:
            continue  # No auth block; git uses ambient credentials — nothing to check.

        if repo.auth.type == "https" and repo.auth.token_env:
            # The token must exist in the environment right now, not just at
            # sync time, because inject_https_token() reads it at the start of
            # import_repo() / export_repo(). A missing token means instant failure.
            if not os.environ.get(repo.auth.token_env):
                issues.append(ValidationIssue(
                    field="auth.token_env",
                    message=f"Environment variable '{repo.auth.token_env}' is not set or empty",
                    severity="error",
                    repo=repo.name,
                ))

        elif repo.auth.type == "ssh" and repo.auth.private_key:
            # The key path was already expanded (~ / $VAR) by the Pydantic
            # validator, so we can check existence directly without re-expanding.
            if not Path(repo.auth.private_key).exists():
                issues.append(ValidationIssue(
                    field="auth.private_key",
                    message=f"SSH key not found: {repo.auth.private_key}",
                    severity="error",
                    repo=repo.name,
                ))

    return issues
