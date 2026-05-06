"""Configuration models and loader for gitbit."""
from __future__ import annotations

import json
import os
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
    submodules: bool = False


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
