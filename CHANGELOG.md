# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-06

### Added
- Initial release of `git-mirror`.
- `sync` subcommand: ad-hoc mirror of a single repo without a config file.
- `sync-all` subcommand: import and export all repos defined in a JSON config.
- `import-all` subcommand: clone or fetch all source repos into local bare mirrors.
- `export-all` subcommand: push all local mirrors to their configured destinations.
- Pydantic v2 config models with full validation (`Config`, `GlobalConfig`, `RepoConfig`, `AuthConfig`).
- SSH authentication via `GIT_SSH_COMMAND` (no interactive prompts, `StrictHostKeyChecking=accept-new`).
- HTTPS authentication via token injected into URL from an environment variable (`token_env`).
- `safe_url()` helper to strip credentials before logging.
- Retry logic with exponential backoff + random jitter via `tenacity` (up to 5 attempts).
- Concurrent execution via `ThreadPoolExecutor` with configurable worker count.
- Pre-clone disk-space check (requires ≥ 1 GB free).
- LFS support: `git lfs fetch --all` / `git lfs push --all` when `lfs: true`.
- `--dry-run` flag that logs all commands without executing them.
- `git gc --auto` helper for mirror maintenance (non-fatal on failure).
- Docker image based on `python:3.11-slim` with `git`, `git-lfs`, and `openssh-client`.
- GitHub Actions CI matrix: Ubuntu + macOS × Python 3.9–3.12 with flake8, mypy, and pytest.
- `src` layout with `hatchling` build backend.
- MIT License.

[Unreleased]: https://github.com/your-org/git-mirror/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/your-org/git-mirror/releases/tag/v0.1.0
