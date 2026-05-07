"""Configuration models and loader for gitbit."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from .exceptions import ConfigError


class AuthConfig(BaseModel):
    type: Literal["ssh", "https"]
    private_key: Optional[str] = None  # path to SSH key; expands ~ and env vars
    token_env: Optional[str] = None  # env var name holding HTTPS token

    @field_validator("private_key")
    @classmethod
    def expand_key_path(cls, v: Optional[str]) -> Optional[str]:
        if v:
            return os.path.expandvars(os.path.expanduser(v))
        return v


class RepoConfig(BaseModel):
    name: str
    source: str
    dest: str
    auth: Optional[AuthConfig] = None
    lfs: bool = False


class GlobalConfig(BaseModel):
    parallel: int = Field(default=4, ge=1, le=32)
    timeout: int = Field(default=300, ge=10)
    verbose: bool = False
    mirrors_dir: str = Field(default="~/.gitbit/mirrors")

    @field_validator("mirrors_dir")
    @classmethod
    def expand_dir(cls, v: str) -> str:
        return os.path.expandvars(os.path.expanduser(v))


class Config(BaseModel):
    global_config: GlobalConfig = Field(default_factory=GlobalConfig, alias="global")
    repos: list[RepoConfig] = []

    model_config = {"populate_by_name": True}


def load_config(path: str) -> Config:
    """Load and validate config from a JSON file."""
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
    field: str
    message: str
    severity: str  # "error" | "warning"
    repo: Optional[str] = None  # None = global-level issue


def validate_config(cfg: Config) -> list[ValidationIssue]:
    """Check config for structural issues, missing env vars, and missing key files.

    Returns a list of ValidationIssue. An empty list means no issues found.
    Makes no network connections.
    """
    issues: list[ValidationIssue] = []

    # Duplicate repo names
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

    # mirrors_dir existence (warning only — created automatically on first import)
    if not Path(cfg.global_config.mirrors_dir).exists():
        issues.append(ValidationIssue(
            field="mirrors_dir",
            message=(
                f"'{cfg.global_config.mirrors_dir}' does not exist"
                " — will be created automatically on first import"
            ),
            severity="warning",
        ))

    # Per-repo auth checks
    for repo in cfg.repos:
        if repo.auth is None:
            continue
        if repo.auth.type == "https" and repo.auth.token_env:
            if not os.environ.get(repo.auth.token_env):
                issues.append(ValidationIssue(
                    field="auth.token_env",
                    message=f"Environment variable '{repo.auth.token_env}' is not set or empty",
                    severity="error",
                    repo=repo.name,
                ))
        elif repo.auth.type == "ssh" and repo.auth.private_key:
            if not Path(repo.auth.private_key).exists():
                issues.append(ValidationIssue(
                    field="auth.private_key",
                    message=f"SSH key not found: {repo.auth.private_key}",
                    severity="error",
                    repo=repo.name,
                ))

    return issues
