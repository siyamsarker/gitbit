"""
gitbit — Mirror Git repositories with full ref fidelity.

This is the root package. It exposes only the version string at this level;
all public functionality lives in the submodules listed below.

Package layout
--------------
gitbit/
  cli.py        Click-based command-line interface. Defines all user-facing
                subcommands (sync-all, import-all, export-all, sync, validate,
                status) and wires them to the sync/config layers.

  config.py     Pydantic v2 configuration models and JSON loader. Defines the
                schema for repos.json, performs field-level validation (type
                coercion, path expansion), and provides validate_config() for
                deeper semantic checks.

  auth.py       Authentication helpers. Builds the GIT_SSH_COMMAND environment
                variable for SSH key auth, injects OAuth2 tokens into HTTPS URLs
                for token-based auth, and sanitises URLs before logging.

  git_ops.py    Low-level Git subprocess wrappers. Every git call in the project
                goes through here. Implements retry logic (tenacity), disk space
                pre-flight checks, auth-error fast-fail, and dry-run support.

  sync.py       High-level sync orchestration. Coordinates import (clone/fetch
                from source) and export (push to destination) per repository,
                runs operations in parallel via ThreadPoolExecutor, and collects
                structured results.

  exceptions.py Custom exception hierarchy rooted at GitMirrorError. Allows
                callers to distinguish auth failures (AuthError) from transient
                git errors (GitOperationError) from configuration errors (ConfigError).

  __main__.py   Enables `python -m gitbit` invocation by delegating to cli.main.
"""

__version__ = "0.2.0"
